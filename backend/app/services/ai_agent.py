"""Voizbot conversacional en tiempo real: FreeSWITCH entrega el control de
la llamada a este servidor (ESL "outbound socket" mode, ver dialplan
`socket backend:8085 async full`), que a su vez arranca `mod_audio_fork`
sobre ese mismo canal para streamear el audio del paciente en vivo.

Pipeline: mod_audio_fork -> /ws/voicebot/{call_id} (este proceso) -> STT
streaming (ElevenLabs Scribe Realtime) -> DeepSeek (decide qué decir/hacer)
-> TTS por frase -> playback nativo de FreeSWITCH, interrumpible con
`uuid_break` si el paciente empieza a hablar mientras el bot responde
(barge-in). Ver AGENT_SYSTEM_PROMPT para el guion.
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.clock import calendario, fecha_en_palabras, hora_en_palabras, now_local
from app.core.config import settings
from app.core.database import async_session
from app.models import Appointment, Debt, PaymentPromise, SystemSettings, Tenant
from app.services import ai_intents, ambience, deepgram, llm, tts, tts_elevenlabs
from app.services.ajustes import ajustes_de
from app.services.numeros import numero_a_palabras
from app.services.usage import UsageMeter
from app.services.appointments import (
    available_slots,
    business_hours_error,
    find_next_appointment,
    is_slot_free,
    parse_date,
    parse_time,
)

logger = logging.getLogger(__name__)

AI_SESSIONS_DIR = "ai_sessions"
FS_SIDE_SOUNDS_DIR = "/usr/share/freeswitch/sounds"
MAX_TURNS = 12
# Cuánto esperar en silencio a que el paciente empiece a hablar antes de
# dar el turno por vacío y colgar (reemplaza al viejo RECORD_TIME_LIMIT +
# umbral de energía: ahora el fin de turno lo decide el VAD del propio
# Scribe Realtime, del lado del servidor, no un temporizador fijo local).
TURN_TIMEOUT_SECONDS = 15
# Segundos de silencio que Scribe espera antes de dar por "confirmado" (fin
# de enunciado) un tramo de habla — equivalente al viejo RECORD_SILENCE_HITS,
# pero evaluado en tiempo real sobre el audio, no como corte de grabación.
VAD_SILENCE_SECS = 0.7
# "Alice" (premade): confirmada usable en plan free. NO usar
# tts_elevenlabs.DEFAULT_VOICES[0] (Rachel) — es una voz de librería
# compartida bloqueada por API en plan free (402 payment_required).
VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"

def _prompt_con_fecha(intencion: ai_intents.Intencion) -> str:
    """Prompt de la gestión + un calendario ya resuelto.

    El tono y las reglas comunes salen de `ai_intents.BASE`; lo que cambia
    por gestión es el bloque `objetivo`. Así confirmar, reagendar y
    cancelar son guiones distintos y no un único agente genérico que tiene
    que adivinar a qué lo llamaron.

    El calendario va aparte porque el modelo calcula mal las fechas: en
    una llamada real dio el 18 (martes) cuando le pidieron "el viernes de
    la próxima semana". Con la tabla, calcular pasa a ser buscar."""
    return (
        f"{intencion.base or ai_intents.BASE}\n\n{intencion.objetivo}\n\n"
        f"CALENDARIO (úsalo SIEMPRE, nunca calcules fechas de memoria):\n"
        f"{calendario(15)}\n\n"
        "Para interpretar 'mañana', 'el viernes', 'la otra semana', 'en quince días', "
        "busca el día en esa tabla y copia la fecha ISO que le corresponde. Si la "
        "persona pide un día que no aparece, pídele que lo precise en vez de "
        "adivinarlo. Antes de confirmar, di siempre el día de la semana junto a la "
        "fecha ('el viernes 21') para que pueda corregirte si no coincide.\n"
        "Al llamar herramientas, las fechas SIEMPRE en formato YYYY-MM-DD y las horas en HH:MM (24h)."
    )


def _local_sessions_dir() -> Path:
    path = Path(settings.fs_sounds_dir) / AI_SESSIONS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


class ESLOutboundSession:
    """Conexión ESL en modo "outbound" (FreeSWITCH conecta HACIA nosotros)
    para UNA llamada. Protocolo mínimo: `connect` para recibir las
    variables del canal, `sendmsg ... event-lock: true` para ejecutar
    aplicaciones de forma bloqueante, y `api` para comandos de una sola
    respuesta (uuid_audio_fork, uuid_break)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.channel_vars: dict[str, str] = {}

    async def _read_message(self) -> tuple[dict, str]:
        headers: dict = {}
        while True:
            line = await self.reader.readline()
            if not line:
                raise ConnectionError("Conexión ESL cerrada por FreeSWITCH")
            decoded = line.decode(errors="replace").rstrip("\r\n")
            if not decoded:
                break
            if ":" in decoded:
                k, _, v = decoded.partition(":")
                headers[k.strip().lower()] = v.strip()
        length = int(headers.get("content-length", 0) or 0)
        body = ""
        if length > 0:
            body = (await self.reader.readexactly(length)).decode(errors="replace")
        return headers, body

    async def connect(self) -> None:
        self.writer.write(b"connect\n\n")
        await self.writer.drain()
        headers, _ = await self._read_message()
        self.channel_vars = headers
        # Suscribirse a los eventos de ESTE canal. Sin esto no hay forma de
        # saber cuándo termina de verdad cada aplicación: `sendmsg` responde
        # "+OK" apenas ENCOLA el comando, no cuando la app finaliza
        # (confirmado en una llamada real: `record` arrancó 20 ms ANTES de
        # que terminara el beep de 200 ms que lo precedía).
        self.writer.write(b"myevents plain\n\n")
        await self.writer.drain()
        await self._read_message()

    @staticmethod
    def _parse_event(body: str) -> dict:
        event: dict = {}
        for line in body.split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                event[k.strip().lower()] = v.strip()
        return event

    async def execute(self, app: str, arg: str = "", timeout: float = 60.0) -> None:
        """Ejecuta una app y ESPERA a que termine (CHANNEL_EXECUTE_COMPLETE)."""
        msg = (
            "sendmsg\n"
            "call-command: execute\n"
            f"execute-app-name: {app}\n"
            f"execute-app-arg: {arg}\n"
            "event-lock: true\n"
            "\n"
        )
        self.writer.write(msg.encode())
        await self.writer.drain()
        await self._read_message()  # "+OK" de encolado, NO de finalización

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                headers, body = await asyncio.wait_for(
                    self._read_message(), timeout=max(1.0, deadline - loop.time())
                )
            except asyncio.TimeoutError:
                return
            if headers.get("content-type") != "text/event-plain":
                continue
            event = self._parse_event(body)
            name = event.get("event-name")
            if name == "CHANNEL_EXECUTE_COMPLETE" and event.get("application") == app:
                return
            if name in ("CHANNEL_HANGUP", "CHANNEL_HANGUP_COMPLETE", "CHANNEL_DESTROY"):
                raise ConnectionError("La llamada fue colgada")

    async def api(self, command: str) -> str:
        """Comando `api` de una sola respuesta (no bloquea a que termine una
        app del canal, solo a que FreeSWITCH ejecute el comando en sí —
        usado para uuid_audio_fork y uuid_break)."""
        self.writer.write(f"api {command}\n\n".encode())
        await self.writer.drain()
        while True:
            headers, body = await self._read_message()
            if headers.get("content-type") == "api/response":
                return body

    async def hangup(self) -> None:
        try:
            self.writer.write(b"api uuid_kill " + self.channel_vars.get("unique-id", "").encode() + b"\n\n")
            await self.writer.drain()
        except Exception:
            pass
        self.writer.close()


# Herramientas que MODIFICAN datos de negocio (agenda o cobranza).
_TOOLS_QUE_MODIFICAN = (
    "agendar_cita", "cancelar_cita", "reagendar_cita", "confirmar_cita", "registrar_promesa",
)
# Palabras con las que el modelo da por hecha una acción.
_AFIRMACIONES = ("cancelad", "agendad", "reagendad", "confirmad", "prometid", "comprometid")

# Detecta que la respuesta le está proponiendo horarios a la persona:
# "a las 10:00", "a las tres de la tarde", "a las once y media".
_HORAS = re.compile(
    r"\b\d{1,2}:\d{2}\b"
    r"|\ba\s+las\s+(?:una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|\d{1,2})\b",
    re.IGNORECASE,
)


async def _llm_turn(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    caller_phone: str,
    meter: UsageMeter,
    tools: list[dict] | None = None,
    appointment_id_fijo: int | None = None,
    tenant_id: int | None = None,
    intencion_key: str = "general",
    call_uuid: str | None = None,
) -> tuple[str, bool]:
    """Le pasa la conversación al modelo de lenguaje configurado en
    Ajustes, ejecuta las tool calls que pida (contra la agenda o la
    cobranza real), y devuelve (texto_para_decir, terminar_llamada)."""
    should_end = False
    reply_text = ""
    hubo_accion = False
    ya_se_reclamo = False
    # ¿Se consultó la agenda en este turno? Si el bot va a nombrar
    # horarios, tienen que salir de una consulta y no de su imaginación.
    hubo_consulta = False
    ya_se_reclamo_horarios = False

    for _ in range(5):  # tope de vueltas tool-call -> tool-call por turno
        message, uso = await llm.chat(base_url, model, api_key, messages, tools=tools)
        meter.llm(uso)
        messages.append(message)
        calls = llm.parse_tool_calls(message)

        if not calls:
            reply_text = message.get("content") or ""
            # Guarda anti-alucinación: el modelo a veces AFIRMA haber hecho
            # la acción sin llegar a llamar la herramienta. Pasó en una
            # llamada real: dijo "Tu cita ha sido cancelada" y la cita
            # seguía activa en la base. Si dice que hizo algo pero no
            # ejecutó ninguna herramienta que modifique, se le exige.
            if (
                not hubo_accion
                and not ya_se_reclamo
                and any(p in reply_text.lower() for p in _AFIRMACIONES)
            ):
                ya_se_reclamo = True
                herramientas = (
                    "registrar_promesa"
                    if intencion_key == "cobranza"
                    else "agendar_cita / cancelar_cita / reagendar_cita"
                )
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "No ejecutaste ninguna herramienta, así que en el sistema NO cambió nada. "
                            "Si la persona ya confirmó, llama AHORA a la herramienta que corresponda "
                            f"({herramientas}). Si todavía falta algún dato, pídeselo — pero no "
                            "afirmes que la acción está hecha."
                        ),
                    }
                )
                continue

            # Guarda anti-invención de horarios. En una llamada real el bot
            # ofreció "las tres de la tarde" sin haber consultado, y esa
            # hora estaba ocupada: al intentar agendarla tuvo que
            # retractarse y la persona respondió "ya te había confirmado
            # que a las tres". Prometer un cupo que no existe es peor que
            # demorarse un segundo en mirarlo. La cobranza no consulta
            # agenda: sus fechas son las de pago, así que el guarda no
            # aplica ahí.
            if (
                intencion_key != "cobranza"
                and not hubo_consulta
                and not ya_se_reclamo_horarios
                and _HORAS.search(reply_text)
            ):
                ya_se_reclamo_horarios = True
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Estás nombrando horarios sin haber consultado la agenda en este turno. "
                            "Llama AHORA a consultar_disponibilidad para ese día y ofrece solo "
                            "horarios que aparezcan en el resultado. No inventes ni supongas cupos."
                        ),
                    }
                )
                continue
            break

        async with async_session() as session:
            promesa_fallida = False
            for call_id, name, args in calls:
                ok, result, info = await _run_tool(
                    session, name, args, caller_phone, appointment_id_fijo, tenant_id, call_uuid
                )
                if name == "terminar_llamada":
                    if promesa_fallida:
                        # El modelo quiere colgar justo después de que
                        # falló registrar_promesa (faltó monto, fecha o el
                        # número de cuotas). Es lo que en una llamada real
                        # se vivió como "me pregunta por las cuotas y se
                        # corta": colgar sin promesa resuelta. Se bloquea y
                        # se le exige conseguir el dato que falta.
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "NO puedes terminar la llamada todavía: el intento de registrar "
                                    "la promesa falló porque faltó algún dato (monto, fecha o número "
                                    "de cuotas). Pregúntale a la persona exactamente lo que falta y "
                                    "vuelve a intentar registrar_promesa. Solo termina cuando la "
                                    "promesa quede registrada o la persona se despida explícitamente."
                                ),
                            }
                        )
                        continue
                    should_end = True
                if name == "consultar_disponibilidad":
                    hubo_consulta = True
                if name in _TOOLS_QUE_MODIFICAN and ok:
                    hubo_accion = True
                    # La llamada dejó algo hecho (cita o promesa de pago):
                    # es lo que separa una conversación resuelta de una que
                    # solo gastó.
                    meter.resolved = True
                    if info:
                        meter.action = info["action"]
                        meter.appointment_id = info.get("appointment_id")
                        meter.action_appointment_date = info.get("appointment_date")
                        meter.action_patient_name = info.get("patient_name")
                if name == "registrar_promesa" and not ok:
                    promesa_fallida = True
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})

    # Si se agotaron las vueltas y el modelo nunca llegó a redactar una
    # respuesta, el bot se quedaba MUDO: handle_call salta el playback
    # (está guardado por `if reply_text`), espera el turno en silencio y
    # cuelga. Acá se le fuerza una última respuesta solo-texto.
    #
    # Esto también pasa (y es peor) cuando el modelo YA llamó a
    # terminar_llamada: en una llamada real, el modelo llamó a
    # confirmar_cita y terminar_llamada juntas, sin texto — colgó sin
    # despedirse. Antes esto se saltaba (`and not should_end`) porque se
    # pensaba solo en "el turno sigue, que no quede en silencio"; pero un
    # silencio en medio de la llamada al menos deja el turno abierto para
    # que la persona hable de nuevo, mientras que colgar sin decir nada
    # no tiene forma de recuperarse.
    if not reply_text:
        try:
            message, uso = await llm.chat(base_url, model, api_key, messages, tool_choice="none", tools=tools)
            meter.llm(uso)
            messages.append(message)
            reply_text = message.get("content") or ""
        except Exception:
            logger.exception("No se pudo forzar la respuesta final del modelo")

    # Último recurso: nunca terminar el turno (ni menos aún colgar) sin
    # decir nada. Un silencio seco y cuelgue es peor que una frase de
    # relleno o de cierre.
    if not reply_text:
        # Genérico y no específico de "confirmar" — este último recurso
        # se comparte con reagendar/cancelar/agendar, así que no puede
        # asumir qué pasó en la llamada (cada gestión ya trae su propio
        # cierre cálido en su `objetivo`; esto solo cubre que el modelo
        # nunca haya llegado a decir nada).
        reply_text = (
            "¡Muchas gracias por tu tiempo! Que tengas buen día."
            if should_end
            else "Perdóname, se me enredó un momento. ¿Me repites lo último, por favor?"
        )

    return reply_text, should_end


async def _buscar_cita(
    session, caller_phone: str, appointment_id: int | None, tenant_id: int | None = None
):
    """Si la llamada trae una cita fijada (campaña, ver
    nspbx_appointment_id), se actúa sobre ESA exactamente. Si no, se cae
    al criterio de siempre (la próxima confirmada de este teléfono) —
    necesario para llamadas entrantes normales, que nunca traen una cita
    fijada de antemano. Con `tenant_id` (el voizbot usa la sesión del
    dueño, sin RLS) la búsqueda se acota a la empresa de la llamada."""
    if appointment_id:
        appt = await session.get(Appointment, appointment_id)
        if appt:
            return appt
    return await find_next_appointment(session, caller_phone, tenant_id=tenant_id)


def _info_accion(accion: str, appt, **extra) -> dict:
    return {
        "action": accion,
        "appointment_id": appt.id if appt is not None else extra.get("appointment_id"),
        "appointment_date": appt.appointment_date if appt is not None else extra.get("appointment_date"),
        "patient_name": appt.patient_name if appt is not None else extra.get("patient_name"),
    }


async def _buscar_deuda(session, caller_phone: str, tenant_id: int) -> Debt | None:
    """La deuda activa de este teléfono en la empresa de la llamada. Se
    busca por teléfono (últimos 10 dígitos, igual que las citas: el mismo
    número llega en formatos distintos) y se cae al saldo pendiente."""
    digits = "".join(c for c in caller_phone if c.isdigit())
    suffix = digits[-10:] if len(digits) >= 10 else digits
    query = select(Debt).where(
        Debt.tenant_id == tenant_id,
        Debt.status.in_(("open", "promised", "overdue")),
    )
    if suffix:
        query = query.where(Debt.phone.like(f"%{suffix}"))
    else:
        query = query.where(Debt.phone == caller_phone)
    query = query.order_by(Debt.updated_at.desc())
    return (await session.execute(query)).scalars().first()


async def _run_tool(
    session,
    name: str,
    args: dict,
    caller_phone: str,
    appointment_id: int | None = None,
    tenant_id: int | None = None,
    call_uuid: str | None = None,
) -> tuple[bool, str, dict | None]:
    """Devuelve (funcionó, mensaje para el modelo, info de la acción o
    None). `info` es lo que necesita el registro de gestión (ver
    AiCallUsage) — solo se llena cuando la herramienta de verdad
    modificó una cita o registró una promesa.

    El éxito se declara explícitamente y NO se deduce del texto. Antes se
    miraba si el mensaje contenía la palabra "error", y ninguno de los
    siete rechazos por regla de negocio la contiene ("Ese horario ya está
    ocupado", "No encontré una cita para cancelar", "El consultorio no
    atiende los domingos"…): todos contaban como gestión hecha. Eso
    inflaba la tasa de contención y, peor, desarmaba la guarda
    anti-alucinación, que se apaga cuando cree que ya hubo una acción.

    Esta sesión es la del DUEÑO (sin RLS), así que todo lo que se lea o
    escriba va filtrado o etiquetado con `tenant_id` explícito — el
    voizbot atiende llamadas de varias empresas en el mismo proceso."""
    try:
        if name == "consultar_disponibilidad":
            d = parse_date(args["date"])
            slots = await available_slots(session, d, tenant_id)
            # Todas las herramientas nombran el día de la semana además de
            # la fecha: si el modelo pidió el 18 cuando el paciente dijo
            # "viernes", ve "martes 18" en la respuesta y puede corregirse
            # antes de confirmarle algo equivocado.
            cuando = fecha_en_palabras(d)
            if not slots:
                return False, f"No hay horarios libres el {cuando}.", None
            return True, f"Horarios libres el {cuando}: {', '.join(slots)}", None

        if name == "agendar_cita":
            from datetime import datetime as dt

            start = dt.combine(parse_date(args["date"]), parse_time(args["time"]))
            motivo = business_hours_error(start, 30)
            if motivo:
                return False, f"{motivo} Ofrécele otro horario.", None
            if not await is_slot_free(session, start, 30, tenant_id):
                return False, "Ese horario ya está ocupado.", None
            appt = Appointment(
                tenant_id=tenant_id,
                patient_name=args["patient_name"],
                phone=caller_phone,
                appointment_date=start,
                status="confirmed",
            )
            session.add(appt)
            try:
                await session.commit()
            except IntegrityError:
                # Otra llamada simultánea ganó el mismo hueco entre el
                # chequeo y el insert (ver el índice ux_appointments_slot).
                await session.rollback()
                return False, "Ese horario acaba de ocuparse. Ofrécele otro.", None
            return (
                True,
                f"Cita agendada para el {fecha_en_palabras(start.date())} a las {start.strftime('%H:%M')}.",
                _info_accion("agendada", appt),
            )

        if name == "confirmar_cita":
            appt = await _buscar_cita(session, caller_phone, appointment_id, tenant_id)
            if not appt:
                return False, "No encontré una cita para confirmar.", None
            cuando = f"{fecha_en_palabras(appt.appointment_date.date())} a las {hora_en_palabras(appt.appointment_date)}"
            appt.confirmed_at = now_local()
            await session.commit()
            return True, f"Cita del {cuando} confirmada por el paciente.", _info_accion("confirmada", appt)

        if name == "cancelar_cita":
            appt = await _buscar_cita(session, caller_phone, appointment_id, tenant_id)
            if not appt:
                return False, "No encontré una cita para cancelar.", None
            cuando = f"{fecha_en_palabras(appt.appointment_date.date())} a las {appt.appointment_date.strftime('%H:%M')}"
            appt.status = "cancelled"
            await session.commit()
            return True, f"Cita del {cuando} cancelada.", _info_accion("cancelada", appt)

        if name == "reagendar_cita":
            from datetime import datetime as dt

            appt = await _buscar_cita(session, caller_phone, appointment_id, tenant_id)
            if not appt:
                return False, "No encontré una cita para reagendar.", None
            new_start = dt.combine(parse_date(args["new_date"]), parse_time(args["new_time"]))
            motivo = business_hours_error(new_start, appt.duration_minutes)
            if motivo:
                return False, f"{motivo} Ofrécele otro horario.", None
            if not await is_slot_free(session, new_start, appt.duration_minutes, tenant_id):
                return False, "Ese nuevo horario ya está ocupado.", None
            appt.appointment_date = new_start
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, "Ese horario acaba de ocuparse. Ofrécele otro.", None
            return (
                True,
                f"Cita reagendada para el {fecha_en_palabras(new_start.date())} a las {new_start.strftime('%H:%M')}.",
                _info_accion("reagendada", appt),
            )

        if name == "registrar_promesa":
            from datetime import datetime as dt

            monto = float(args.get("monto") or 0)
            if monto <= 0:
                return False, "El monto prometido debe ser mayor que cero.", None
            try:
                fecha = parse_date(args["fecha"])
            except KeyError:
                return False, "Falta la fecha prometida de pago.", None
            plan = str(args.get("tipo") or "completo").lower()
            if plan not in ("completo", "abono", "cuotas"):
                return False, "El tipo de promesa debe ser completo, abono o cuotas.", None
            cuotas = None
            if plan == "cuotas":
                cuotas = int(args.get("cuotas") or 0)
                if cuotas <= 0:
                    return False, "Falta el número de cuotas del plan.", None
            deuda = await _buscar_deuda(session, caller_phone, tenant_id)
            promesa = PaymentPromise(
                tenant_id=tenant_id,
                debt_id=deuda.id if deuda else None,
                phone=caller_phone,
                debtor_name=args.get("cliente") or (deuda.debtor_name if deuda else None),
                amount_promised=monto,
                promise_date=dt.combine(fecha, dt.min.time()),
                plan=plan,
                installments=cuotas,
                notes=args.get("nota"),
                status="pending",
                call_uuid=call_uuid,
            )
            session.add(promesa)
            if deuda:
                deuda.status = "promised"
            await session.commit()
            await session.refresh(promesa)
            cuando = fecha_en_palabras(fecha)
            if plan == "cuotas":
                texto = f"Promesa registrada: {int(monto):,} pesos en {cuotas} cuotas, primer pago el {cuando}."
            elif plan == "abono":
                texto = f"Promesa registrada: abono de {int(monto):,} pesos el {cuando}."
            else:
                texto = f"Promesa registrada: pago de {int(monto):,} pesos el {cuando}."
            return (
                True,
                texto,
                {
                    "action": f"promesa_{plan}",
                    "appointment_id": None,
                    "appointment_date": promesa.promise_date,
                    "patient_name": promesa.debtor_name,
                    "promise_id": promesa.id,
                },
            )

        if name == "terminar_llamada":
            return True, "Llamada finalizada.", None
    except Exception as exc:
        logger.exception("Error ejecutando tool %s", name)
        return False, f"Ocurrió un error interno: {exc}", None
    return False, "Herramienta desconocida.", None


class ThinkingSound:
    """El tecleo que rellena el silencio mientras el bot consulta.

    Va con `uuid_broadcast` y no con `playback`: broadcast no bloquea, así
    que el loop puede consultar al modelo y sintetizar la voz mientras el
    sonido corre, y se corta con `uuid_break` en cuanto hay algo que decir.
    Con `playback` (que sí espera a terminar) el relleno retrasaría
    justamente la respuesta que está tapando."""

    def __init__(self, session: ESLOutboundSession, path: str | None):
        self.session = session
        self.path = path
        self._sonando = False

    async def start(self) -> None:
        if self._sonando or not self.path:
            return
        self._sonando = True
        uid = self.session.channel_vars.get("unique-id", "")
        try:
            await self.session.api(f"uuid_broadcast {uid} {self.path} aleg")
        except Exception:
            # El relleno es un adorno: si falla, la llamada sigue en silencio
            # como antes, pero sigue.
            self._sonando = False
            logger.warning("No se pudo arrancar el tecleo de fondo")

    async def stop(self) -> None:
        """Idempotente: se llama sin miedo desde varios puntos del turno."""
        if not self._sonando:
            return
        self._sonando = False
        uid = self.session.channel_vars.get("unique-id", "")
        try:
            await self.session.api(f"uuid_break {uid} all")
        except Exception:
            pass


class CallBridge:
    """Puente entre la sesión ESL outbound (que controla la llamada) y el
    websocket de audio (que recibe el stream de mod_audio_fork). Vive
    mientras dura la llamada, indexado por call_id en `active_bridges`."""

    def __init__(self, scribe: tts_elevenlabs.ScribeRealtimeSession, meter: UsageMeter):
        self.scribe = scribe
        self.meter = meter
        self.utterances: asyncio.Queue[str | None] = asyncio.Queue()
        # Se activa con CUALQUIER transcripción parcial — señal de que el
        # paciente está hablando, usada para el barge-in mientras el bot
        # reproduce su respuesta.
        self.speech_detected = asyncio.Event()


active_bridges: dict[str, CallBridge] = {}

router = APIRouter()


@router.websocket("/ws/voicebot/{call_id}")
async def voicebot_audio_ws(websocket: WebSocket, call_id: str) -> None:
    """Recibe el audio del canal que manda mod_audio_fork (PCM L16, 8kHz,
    mono) y lo reenvía al STT streaming de ElevenLabs. El primer mensaje que
    manda el módulo es un frame de TEXTO con la metadata que le pasamos en
    `uuid_audio_fork ... start`; de ahí en más son frames binarios de audio."""
    await websocket.accept()
    bridge = active_bridges.get(call_id)
    if bridge is None:
        logger.warning("Voizbot IA: llegó audio de %s sin sesión activa, cerrando websocket", call_id)
        await websocket.close()
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                try:
                    bridge.meter.stt(len(message["bytes"]))
                    await bridge.scribe.send_audio(message["bytes"])
                except Exception:
                    # Si el websocket de Scribe se cayó (blip de red, etc.),
                    # que no reviente TODO el forwarding de audio de golpe:
                    # _consume_transcripts ya recibe el sentinel "_closed" y
                    # cuelga la llamada limpio por su cuenta (ver
                    # handle_call). Acá solo se loguea una vez y se corta
                    # este loop, sin traceback ruidoso repetido por chunk.
                    logger.warning("Voizbot IA: se perdió el STT streaming de %s", call_id)
                    break
            # el resto (texto: metadata inicial de mod_audio_fork) no aporta nada acá
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Voizbot IA: error en websocket de audio de %s", call_id)


# Umbral mínimo de texto para considerar un partial_transcript como habla
# real del paciente. En llamadas reales por troncal, el ruido de fondo
# (televisión, voces lejanas, el eco de la propia línea) se filtra en el
# audio que mod_audio_fork captura y Scribe la transcribe como fragmentos
# cortos ("a a a", "mm", "bueno") — con un umbral bajo, ese ruido disparaba
# el barge-in y el bot se cortaba solo a mitad de frase, se trababa y
# sonaba como que no dejaba hablar. Se exige un tramo claramente más largo:
# una interrupción real ("no, espera", "me sirve en cuotas") lo supera,
# el ruido de fondo casi nunca. Antes estaba en 4 y no alcanzaba.
_MIN_BARGEIN_CHARS = 12


async def _consume_transcripts(bridge: CallBridge) -> None:
    """Tarea de fondo: clasifica los eventos de Scribe Realtime en
    "el paciente está hablando" (barge-in) y "turno completo" (utterance)."""
    while True:
        event = await bridge.scribe.events.get()
        mtype = event.get("message_type")
        if mtype == "partial_transcript" and len((event.get("text") or "").strip()) >= _MIN_BARGEIN_CHARS:
            bridge.speech_detected.set()
        elif mtype in ("committed_transcript", "committed_transcript_with_timestamps"):
            text = (event.get("text") or "").strip()
            if text:
                await bridge.utterances.put(text)
        elif mtype == "_closed":
            await bridge.utterances.put(None)
            return


async def _wait_utterance(bridge: CallBridge, timeout: float) -> str | None:
    try:
        return await asyncio.wait_for(bridge.utterances.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def _play_sentence(session: ESLOutboundSession, path: str, bridge: CallBridge) -> bool:
    """Reproduce una frase, cortándola con `uuid_break` en cuanto el
    paciente empieza a hablar de vuelta (barge-in). Devuelve True si hubo
    interrupción."""
    uid = session.channel_vars.get("unique-id", "")
    bridge.speech_detected.clear()
    play_task = asyncio.create_task(session.execute("playback", path))

    # Período de gracia: ignorar barge-in en los primeros ~400ms de cada
    # frase (sin dejar de reproducir). La cola de audio del eco de línea
    # (ver _MIN_BARGEIN_CHARS) tiende a filtrarse justo al arrancar el
    # nuevo playback, encima de la respuesta anterior — confirmado en una
    # llamada real por troncal PSTN. shield() evita que el timeout del
    # wait_for cancele play_task; si la frase es más corta que el período
    # de gracia, play_task ya habrá terminado normal para acá.
    try:
        await asyncio.wait_for(asyncio.shield(play_task), timeout=0.4)
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass  # se re-lanza más abajo al hacer `await play_task`

    bridge.speech_detected.clear()
    if play_task.done():
        await play_task  # deja que se propague cualquier excepción real (p.ej. colgó)
        return False

    watch_task = asyncio.create_task(bridge.speech_detected.wait())
    await asyncio.wait({play_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)

    if watch_task.done() and not play_task.done():
        # CRÍTICO: hay que dejar de leer del stream ESL con play_task ANTES
        # de que session.api() lea su respuesta — dos corutinas leyendo el
        # mismo StreamReader a la vez revienta con "readuntil() called
        # while another coroutine is already waiting for incoming data"
        # (confirmado con una llamada real). Cancelar play_task solo corta
        # NUESTRA lectura de sus eventos; el audio en el teléfono lo corta
        # uuid_break.
        play_task.cancel()
        try:
            await play_task
        except (asyncio.CancelledError, Exception):
            pass
        await session.api(f"uuid_break {uid} all")
        return True

    watch_task.cancel()
    try:
        await watch_task
    except asyncio.CancelledError:
        pass
    await play_task  # deja que se propague cualquier excepción real (p.ej. colgó)
    return False


# Tope de caracteres del PRIMER trozo que se sintetiza. Solo ese manda en
# el silencio que percibe el paciente: mientras suena, los siguientes se
# van generando por detrás. Con Deepgram la síntesis tarda ~25 ms por
# carácter (medido: 18 car → 1,1 s; 200 car → 5,3 s), así que una primera
# frase larga se traduce en varios segundos de nada antes de que el bot
# abra la boca. 60 caracteres ≈ 1,5 s de espera.
_MAX_PRIMER_TROZO = 60


def _trocear(reply_text: str) -> list[str]:
    """Parte la respuesta en frases, y si la primera es larga la corta
    además por coma para que el bot arranque antes.

    Solo se subdivide la primera: las demás se sintetizan mientras suena
    la anterior, y trocearlas de más sería meter pausas sin ganar nada."""
    frases = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", reply_text.strip()) if s.strip()]
    if not frases or len(frases[0]) <= _MAX_PRIMER_TROZO:
        return frases

    primera = frases[0]
    corte = primera.rfind(",", 0, _MAX_PRIMER_TROZO)
    # Sin coma útil no se parte: cortar a mitad de una idea suena peor que
    # esperar un poco más.
    if corte < 20:
        return frases
    return [primera[: corte + 1].strip(), primera[corte + 1 :].strip(), *frases[1:]]


async def _decir_respuesta(
    session: ESLOutboundSession,
    decir,
    reply_text: str,
    bridge: CallBridge,
    turn_key: str,
    allow_bargein: bool = True,
    thinking: "ThinkingSound | None" = None,
) -> bool:
    """Trocea la respuesta por frase y las va reproduciendo en cadena,
    sintetizando la siguiente mientras suena la actual (baja el tiempo hasta
    el primer sonido vs. sintetizar todo el texto de una sola vez). Corta
    apenas hay barge-in. Devuelve True si el paciente interrumpió.

    allow_bargein=False para la despedida final (should_end): no tiene
    sentido dejar que un ruido de fondo la corte a mitad de frase si de
    todos modos la llamada termina ahí — se vivió en una llamada real
    ("se cortó justo al confirmar fecha y hora", el bot se autointerrumpió
    diciendo su propia despedida)."""
    sentences = _trocear(reply_text)
    if not sentences:
        return False

    synth_task = asyncio.create_task(decir(sentences[0], f"{turn_key}_s0"))
    for i, _sentence in enumerate(sentences):
        path = await synth_task
        # El tecleo se corta acá y no antes: mientras se sintetizaba esta
        # frase el silencio seguía existiendo, así que el relleno tiene que
        # durar hasta el instante justo previo a que el bot hable.
        if thinking is not None:
            await thinking.stop()
        if i + 1 < len(sentences):
            synth_task = asyncio.create_task(decir(sentences[i + 1], f"{turn_key}_s{i + 1}"))
        if allow_bargein:
            interrupted = await _play_sentence(session, path, bridge)
        else:
            await session.execute("playback", path)
            interrupted = False
        if interrupted:
            if i + 1 < len(sentences):
                synth_task.cancel()
            return True
    return False


async def handle_call(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    session = ESLOutboundSession(reader, writer)
    try:
        await session.connect()
    except Exception:
        logger.exception("No se pudo establecer la sesión ESL outbound")
        writer.close()
        return

    call_id = session.channel_vars.get("unique-id", str(uuid.uuid4()))
    # El número del CLIENTE, que es con el que se busca su cita.
    # En SALIENTE (campaña) el caller ID es el del PBX, no el del paciente:
    # el número real lo fija `esl.originate` en `nspbx_customer`. En
    # ENTRANTE el cliente sí es quien llama, así que vale el ANI.
    # (Antes se leía solo el ANI y acertaba por accidente, porque el
    # originate estaba metiendo el número marcado en el campo de caller ID.)
    caller_phone = (
        session.channel_vars.get("variable_nspbx_customer")
        or session.channel_vars.get("variable_caller_ani")
        or session.channel_vars.get("caller-caller-id-number")
        or "desconocido"
    )
    logger.info("Voizbot IA: nueva llamada %s de %s", call_id, caller_phone)

    # Saludo personalizado de una campaña de confirmación (ver
    # workers/dialer.py) — reemplaza SOLO la primera frase; el resto de la
    # conversación (tools, objetivo) sigue siendo el de la intención normal.
    saludo_campana = session.channel_vars.get("variable_nspbx_greeting")
    if saludo_campana:
        saludo_campana = unquote(saludo_campana)

    # Cita EXACTA que esta llamada de campaña sincronizó en la Agenda (ver
    # CampaignNumber.appointment_id, cargado en workers/dialer.py). Con
    # esto confirmar_cita/cancelar_cita/reagendar_cita actúan sobre ESA
    # cita puntual en vez de adivinar "la próxima confirmada de este
    # teléfono" — que falla de verdad cuando el mismo número tiene más de
    # una cita a la vez (pasa, y ya causó una confusión real).
    appointment_id_fijo: int | None = None
    _raw_appt_id = session.channel_vars.get("variable_nspbx_appointment_id")
    if _raw_appt_id:
        try:
            appointment_id_fijo = int(_raw_appt_id)
        except ValueError:
            pass

    # De qué EMPRESA es esta llamada. En campaña lo fija el dialer
    # (nspbx_tenant_id); en un flujo del menú lo fija el dialplan (ver
    # flow_engine). Si no llega (llamada vieja), se cae a la única empresa
    # de la instalación — y si hay varias, es un error: no se puede
    # leer ajustes de cualquiera.
    tenant_id: int | None = None
    _raw_tid = session.channel_vars.get("variable_nspbx_tenant_id")
    if _raw_tid:
        try:
            tenant_id = int(_raw_tid)
        except ValueError:
            tenant_id = None
    if tenant_id is None:
        async with async_session() as db:
            tenantes = (await db.execute(select(Tenant.id))).scalars().all()
        if len(tenantes) == 1:
            tenant_id = tenantes[0]
        elif not tenantes:
            logger.error("Voizbot IA: no hay ninguna empresa configurada")
            await session.execute("hangup", "NORMAL_CLEARING")
            return

    async with async_session() as db:
        row = await ajustes_de(db, tenant_id)
        eleven_key = (row.elevenlabs_api_key if row else None) or ""
        deepgram_key = (row.deepgram_api_key if row else None) or ""
        llm_base_url = (getattr(row, "ai_llm_base_url", None) if row else None) or "https://api.deepseek.com/v1"
        llm_model = (getattr(row, "ai_llm_model", None) if row else None) or "deepseek-chat"
        llm_key = (getattr(row, "ai_llm_api_key", None) if row else None) or ""
        llm_provider_name = (getattr(row, "ai_llm_provider_name", None) if row else None) or "el modelo de lenguaje"
        voz_proveedor = (row.ai_voice_provider if row else None) or "elevenlabs"
        stt_proveedor = (getattr(row, "ai_stt_provider", None) if row else None) or "elevenlabs"
        voz_id = (row.ai_voice_id if row else None) or VOICE_ID

    # Cada pieza necesita su propia key, y solo la del proveedor elegido.
    falta = []
    if not llm_key:
        falta.append(llm_provider_name)
    if stt_proveedor == "deepgram" and not deepgram_key:
        falta.append("Deepgram (transcripción)")
    if stt_proveedor == "elevenlabs" and not eleven_key:
        falta.append("ElevenLabs (transcripción)")
    if voz_proveedor == "deepgram" and not deepgram_key:
        falta.append("Deepgram (voz)")
    if voz_proveedor == "elevenlabs" and not eleven_key:
        falta.append("ElevenLabs (voz)")
    if falta:
        logger.error("Voizbot IA: falta configurar en Ajustes: %s", ", ".join(falta))
        await session.execute("hangup", "NORMAL_CLEARING")
        return

    async def decir(texto: str, nombre: str) -> str:
        """Genera el audio de una frase con el proveedor configurado en
        Ajustes. edge-tts es gratis; ElevenLabs suena mejor pero cuesta
        ~15x más por llamada.

        La extensión importa: ElevenLabs se pide en PCM y se envuelve en
        WAV; edge-tts devuelve MP3 (que mod_shout reproduce bien, es el
        mismo audio que ya usan los flujos IVR)."""
        meter.tts(texto)
        if voz_proveedor == "edge":
            audio, ext = await tts.synthesize(texto, voz_id), "mp3"
        elif voz_proveedor == "deepgram":
            audio, ext = await deepgram.synthesize(texto, voz_id, deepgram_key), "wav"
        else:
            audio, ext = await tts_elevenlabs.synthesize(texto, voz_id, eleven_key), "wav"
        local = sessions_dir / f"{nombre}.{ext}"
        local.write_bytes(audio)
        return f"{FS_SIDE_SOUNDS_DIR}/{AI_SESSIONS_DIR}/{local.name}"

    # Qué gestión viene a resolver esta llamada. La fija el dialplan al
    # entregar el control (ver flow_engine), según la tecla que marcó la
    # persona en el menú. Sin esto el bot preguntaba "¿en qué te puedo
    # ayudar?" a alguien que acababa de marcar exactamente eso.
    intencion = ai_intents.obtener(session.channel_vars.get("variable_nspbx_ai_intent"))
    tools_intencion = llm.tools_para(intencion.tools)
    logger.info("Voizbot IA: llamada %s con la gestión '%s'", call_id, intencion.key)

    messages = [{"role": "system", "content": _prompt_con_fecha(intencion)}]
    sessions_dir = _local_sessions_dir()
    consumer_task: asyncio.Task | None = None
    meter = UsageMeter(call_id, caller_phone, voz_proveedor, stt_proveedor, tenant_id)

    try:
        # Las dos sesiones exponen la misma interfaz (cola `events` +
        # `send_audio`), así que el resto del loop es idéntico con
        # cualquiera de los dos proveedores.
        abrir_stt = (
            deepgram.DeepgramRealtimeSession(deepgram_key, sample_rate=8000, silence_secs=VAD_SILENCE_SECS)
            if stt_proveedor == "deepgram"
            else tts_elevenlabs.ScribeRealtimeSession(eleven_key, sample_rate=8000, silence_secs=VAD_SILENCE_SECS)
        )
        async with abrir_stt as scribe:
            bridge = CallBridge(scribe, meter)
            active_bridges[call_id] = bridge
            consumer_task = asyncio.create_task(_consume_transcripts(bridge))
            thinking = ThinkingSound(session, ambience.ensure_typing_loop())

            await session.execute("answer")

            ws_url = f"{settings.voicebot_ws_base}/{call_id}"
            uid = session.channel_vars.get("unique-id", "")
            await session.api(f"uuid_audio_fork {uid} start {ws_url} mono 8k voizbot")

            # La cita (o la deuda, para cobranza) se busca ANTES de
            # saludar: el saludo puede nombrar la fecha real, y el modelo
            # arranca sabiéndola, sin gastar un turno consultándola.
            async with async_session() as db:
                deuda = None
                if intencion.key == "cobranza":
                    deuda = await _buscar_deuda(db, caller_phone, tenant_id)
                    if deuda:
                        monto = f"{int(deuda.amount):,}".replace(",", ".")
                        bloque_deuda = (
                            f"\n\nDEUDA DE LA PERSONA QUE LLAMA — CONFIDENCIAL. NO la reveles (monto, "
                            f"vencimiento, factura) hasta que la persona confirme que es "
                            f"{deuda.debtor_name} o una persona autorizada. Si quien contesta dice "
                            f"no ser el titular, no des ningún dato y termina la llamada con cortesía.\n"
                            f"- Titular: {deuda.debtor_name}\n"
                            f"- Monto adeudado: {monto} pesos\n"
                        )
                        if deuda.due_date:
                            bloque_deuda += f"- Vencimiento: {fecha_en_palabras(deuda.due_date.date())} ({deuda.due_date.date().isoformat()})\n"
                        if deuda.invoice_number:
                            bloque_deuda += f"- Factura / número de cuenta: {deuda.invoice_number}\n"
                        if deuda.notes:
                            bloque_deuda += f"- Nota: {deuda.notes}\n"
                        bloque_deuda += (
                            "\nYa conoces esta deuda: NO la leas de nuevo salvo que la persona lo pida. "
                            "Di los montos en pesos, de forma natural ('doscientos cincuenta mil pesos'), "
                            "nunca número por número."
                        )
                        messages[0]["content"] += bloque_deuda
                else:
                    cita = await db.get(Appointment, appointment_id_fijo) if appointment_id_fijo else None
                    if cita is None:
                        cita = await find_next_appointment(db, caller_phone, tenant_id=tenant_id)

            if intencion.key != "cobranza":
                if cita:
                    cuando = f"{fecha_en_palabras(cita.appointment_date.date())} a las {hora_en_palabras(cita.appointment_date)}"
                    messages[0]["content"] += (
                        f"\n\nLa persona que llama tiene una cita agendada para el {cuando}"
                        f" a nombre de {cita.patient_name}. Ya se la mencionaste al saludar, "
                        "así que no la repitas como si fuera nueva."
                    )
                elif intencion.requiere_cita:
                    # La gestión no tiene sentido sin cita (confirmar, mover o
                    # cancelar algo que no existe). Se avisa y se corta, en vez
                    # de dejar al bot improvisando.
                    logger.info("Voizbot IA: %s pidió '%s' pero no tiene cita", caller_phone, intencion.key)
                    await _decir_respuesta(
                        session, decir,
                        "¡Hola! Te habla la asistente virtual del Centro Odontológico. "
                        "No encuentro ninguna cita agendada a tu nombre. "
                        "Comunícate con nosotros y con mucho gusto te ayudamos. ¡Hasta pronto!",
                        bridge, f"{call_id}_sincita", allow_bargein=False, thinking=thinking,
                    )
                    meter.outcome = "no_appointment"
                    await session.execute("hangup", "NORMAL_CLEARING")
                    return
            elif deuda is None:
                # Cobranza sin deuda registrada para este teléfono: no hay
                # nada que gestionar, se avisa y se corta limpio.
                logger.info("Voizbot IA: %s pidió 'cobranza' pero no tiene deuda", caller_phone)
                await _decir_respuesta(
                    session, decir,
                    "¡Hola! Te llamo por un asunto de cobranza, pero no encuentro "
                    "ninguna deuda registrada a tu nombre. Disculpa la molestia, ¡hasta luego!",
                    bridge, f"{call_id}_sindeuda", allow_bargein=False, thinking=thinking,
                )
                meter.outcome = "no_debt"
                await session.execute("hangup", "NORMAL_CLEARING")
                return

            if intencion.key == "cobranza":
                # BLINDAJE: el saludo NO revela la deuda. Solo identifica al
                # titular; los detalles se dan recién cuando la persona
                # confirma identidad (ver ai_intents.COBRANZA_BASE). Se
                # ignora el message_template de la campaña a propósito:
                # quien lo escribió pudo haberle puesto {monto} o
                # {vencimiento}, y eso filtraría la deuda a un tercero que
                # conteste.
                if deuda and deuda.debtor_name:
                    greeting = (
                        "¡Hola! Te hablo de la empresa por un asunto de cobranza. "
                        f"¿Me confirmas si hablo con {deuda.debtor_name}?"
                    )
                else:
                    greeting = (
                        "¡Hola! Te hablo de la empresa por un asunto de cobranza. "
                        "¿Me confirmas si hablo con el titular de la cuenta?"
                    )
            else:
                greeting = saludo_campana or intencion.saludo(cita)
            await _decir_respuesta(session, decir, greeting, bridge, f"{call_id}_greeting")
            messages.append({"role": "assistant", "content": greeting})

            # ¿Aló? de arranque: mucha gente contesta y tarda unos segundos
            # en hablar (o la línea tiene un eco del contestar). Sin esto,
            # un silencio de 15 s en el primer turno hacía que el bot se
            # despidiera sin haber provocado a la persona — se vivió en una
            # llamada real que se contestó y murió muda. Se da UN aviso
            # corto antes de rendirse.
            nudge_hecho = False
            for turn in range(intencion.max_turns):
                transcript = None
                while transcript is None:
                    raw = await _wait_utterance(bridge, timeout=TURN_TIMEOUT_SECONDS)
                    if raw is None:
                        # Silencio real (no dijo nada) o se cayó el stream de audio.
                        if turn == 0 and not nudge_hecho:
                            nudge_hecho = True
                            await _decir_respuesta(
                                session, decir,
                                "¿Aló? ¿Me escuchas?",
                                bridge, f"{call_id}_nudge", allow_bargein=True, thinking=thinking,
                            )
                            continue
                        meter.outcome = "no_speech" if turn == 0 else "completed"
                        await session.execute("hangup", "NORMAL_CLEARING")
                        return
                    if raw.strip():
                        transcript = raw.strip()

                meter.turns += 1
                messages.append({"role": "user", "content": transcript})

                # Desde acá y hasta que el bot hable hay un hueco real
                # (modelo + herramientas + síntesis). Se rellena con el
                # tecleo para que no sea un silencio muerto.
                await thinking.start()
                reply_text, should_end = await _llm_turn(
                    llm_base_url, llm_model, llm_key, messages, caller_phone, meter, tools_intencion,
                    appointment_id_fijo, tenant_id, intencion.key, call_id,
                )

                if reply_text:
                    await _decir_respuesta(
                        session, decir, reply_text, bridge, f"{call_id}_reply{turn}",
                        allow_bargein=not should_end, thinking=thinking,
                    )
                await thinking.stop()  # por si no hubo nada que decir

                if should_end:
                    meter.outcome = "completed"
                    await session.execute("hangup", "NORMAL_CLEARING")
                    break
            else:
                # Se acabaron los turnos sin que el modelo cerrara: la
                # conversación se fue de largo y conviene poder verlo.
                meter.outcome = "max_turns"
                await session.execute("hangup", "NORMAL_CLEARING")

    except (ConnectionError, asyncio.IncompleteReadError):
        logger.info("Voizbot IA: la llamada %s colgó", call_id)
    except Exception:
        meter.outcome = "error"
        logger.exception("Voizbot IA: error en la conversación %s", call_id)
        try:
            await session.execute("hangup", "NORMAL_CLEARING")
        except Exception:
            pass
    finally:
        # En el finally para que quede registro pase lo que pase: también
        # cuentan (y sobre todo cuentan) las llamadas que terminaron mal.
        await meter.save()
        active_bridges.pop(call_id, None)
        if consumer_task:
            consumer_task.cancel()
        try:
            writer.close()
        except Exception:
            pass


async def start_server(host: str = "0.0.0.0", port: int = 8085) -> asyncio.AbstractServer:
    server = await asyncio.start_server(handle_call, host, port)
    logger.info("Voizbot IA (ESL outbound) escuchando en %s:%s", host, port)
    return server
