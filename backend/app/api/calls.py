"""Historial de llamadas (CDR).

FreeSWITCH envía un JSON al terminar cada llamada (mod_json_cdr apuntando a
POST /fs/cdr, ver freeswitch/conf/autoload_configs/json_cdr.conf.xml) y acá
se normaliza y guarda. Antes la tabla `call_logs` existía pero nadie la
llenaba: no había forma de ver el historial en la app.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere, usuario_actual, verificar_secreto_fs
from app.core.config import settings
from app.core.database import get_admin_session, get_session
from app.models import AiCallUsage, CallLog, Tenant, User
from app.schemas import CallLogOut
from app.services import deepgram, llm
from app.services.ajustes import ajustes_de

logger = logging.getLogger(__name__)

router = APIRouter(tags=["calls"])

# Mismo directorio que /var/lib/freeswitch/recordings del contenedor de
# FreeSWITCH, montado acá con otro nombre (ver docker-compose.yml). Vive en
# app.core.config y no como constante propia para que el limpiador de
# retención (app/workers/maintenance.py) mire exactamente el mismo lugar.
RECORDINGS_DIR = settings.recordings_dir


_RUTA_GRABACION_RE = re.compile(r"^[A-Za-z0-9_./-]{1,300}$")


def _ruta_grabacion_valida(ruta: str | None) -> str | None:
    """La ruta llega en el CDR de FreeSWITCH: se guarda solo si es de la carpeta
    de grabaciones, sin `..` y con caracteres normales."""
    if not ruta:
        return None
    prefijo = settings.fs_recordings_dir.rstrip("/") + "/"
    if not ruta.startswith(prefijo) or ".." in ruta or not _RUTA_GRABACION_RE.fullmatch(ruta):
        logger.warning("CDR con ruta de grabación rechazada: %r", ruta[:200])
        return None
    return ruta


def _local_recording_path(recording_path: str) -> Path:
    """`recording_path` trae la ruta tal como la ve FreeSWITCH
    ($${recordings_dir}/AAAA/MM/DD/llamada_uuid.wav, o solo
    $${recordings_dir}/uuid.wav en grabaciones de antes de organizarlas
    por fecha) — hay que pelarle ese prefijo (el de OTRO contenedor) y
    pegarle el mount point local, conservando las subcarpetas de fecha si
    las trae. Quedarse solo con el nombre del archivo (como antes) rompía
    la reproducción/descarga en cuanto la ruta pasó a tener subcarpetas."""
    prefijo = settings.fs_recordings_dir.rstrip("/") + "/"
    relativa = recording_path[len(prefijo):] if recording_path.startswith(prefijo) else Path(recording_path).name
    base = Path(RECORDINGS_DIR).resolve()
    candidata = (base / relativa).resolve()
    # Un `..` o un enlace simbólico en la ruta guardada no puede sacar la lectura
    # de la carpeta de grabaciones (se serviría, p. ej., /etc/passwd como "audio").
    if base not in candidata.parents or candidata.suffix.lower() != ".wav":
        logger.warning("Ruta de grabación fuera de la carpeta permitida: %r", recording_path[:200])
        return base / ".no-valida"
    return candidata

# Los internos de FreeSWITCH (bot_N, contextos del IVR, la cola) no son
# "el número al que se llamó" desde el punto de vista del usuario.
_INTERNAL_DESTS = ("go", "x")

# /fs/cdr queda fuera de este guardia: lo llama FreeSWITCH al colgar, sin
# sesión. Por eso el permiso va endpoint por endpoint y no en el router.
# Además del permiso de ver llamadas, exige el módulo "pbx" de la empresa
# (modelo de packs — ver Tenant.modules): sin él, una empresa que solo
# contrató voicebot no ve el historial.
async def _ver_pbx(
    usuario: User = Depends(requiere(permissions.LLAMADAS_VER_PROPIAS)),
    session: AsyncSession = Depends(get_session),
) -> User:
    if usuario.tenant_id is not None:
        ten = await session.get(Tenant, usuario.tenant_id)
        if not ten or not ten.has_module("pbx"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu empresa no tiene este módulo activo",
            )
    return usuario


_VER = Depends(_ver_pbx)


def _solo_suyas(usuario: User) -> str | None:
    """Número de extensión al que hay que limitar el historial, o None si
    la persona puede ver todas.

    Un asesor solo tiene por qué ver las llamadas que pasaron por su
    línea; el historial completo incluye las de sus compañeros y las de
    los pacientes que atendió otro.
    """
    if permissions.puede(usuario.role, permissions.LLAMADAS_VER_TODAS):
        return None
    # Sin extensión asignada no hay nada que le corresponda: se devuelve
    # un número imposible para que el filtro no coincida con nada, en vez
    # de dejar pasar todo el historial.
    return usuario.extension.number if usuario.extension else "\x00"


def _acotar(query, propia: str | None):
    if propia is None:
        return query
    return query.where((CallLog.caller_number == propia) | (CallLog.callee_number == propia))


async def _traer(call_id: int, session: AsyncSession, usuario: User) -> CallLog:
    """La llamada, siempre que le corresponda a quien la pide.

    Responde 404 y no 403 cuando la llamada existe pero es de otro: un 403
    confirmaría que ese identificador existe, y con eso se puede recorrer
    el historial ajeno de a uno.
    """
    call = await session.get(CallLog, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    propia = _solo_suyas(usuario)
    if propia is not None and propia not in (call.caller_number, call.callee_number):
        raise HTTPException(status_code=404, detail="Llamada no encontrada")
    return call


def _epoch_us_to_dt(value) -> datetime | None:
    try:
        micros = int(value or 0)
    except (TypeError, ValueError):
        return None
    if micros <= 0:
        return None
    return datetime.utcfromtimestamp(micros / 1_000_000)


def _status_from(cause: str, billsec: int) -> str:
    if billsec > 0:
        return "answered"
    return {
        "NO_ANSWER": "no_answer",
        "USER_BUSY": "busy",
        "ORIGINATOR_CANCEL": "cancelled",
        "NO_USER_RESPONSE": "no_answer",
        "CALL_REJECTED": "rejected",
    }.get(cause, "failed")


@router.post("/fs/cdr/{secret}")
async def receive_cdr(secret: str, request: Request, session: AsyncSession = Depends(get_admin_session)):
    """Recibe el CDR que envía FreeSWITCH al colgar cada llamada.

    Lleva el MISMO secreto compartido que /fs/directory y /fs/dialplan
    (ver json_cdr.conf.xml): sin él, y como esta ruta no cuelga de /api/
    y por lo tanto se salta el guardia global de sesión, cualquiera que
    alcanzara el puerto publicado del backend podía insertar llamadas
    inventadas en el historial — comprobado en una auditoría con un POST
    sin token que quedó guardado en call_logs.

    El secreto va en la RUTA y no en la query string (como sí lo hacen
    /fs/directory y /fs/dialplan) porque mod_json_cdr le agrega SIEMPRE
    su propio "?uuid=..." a la URL configurada: con el secreto en la
    query quedaba "?secret=XXX?uuid=YYY", el valor llegaba con el uuid
    pegado, no coincidía nunca y TODOS los CDR se rechazaban con 403
    (verificado en vivo: los CDR terminaban en json_cdr_failed/ y el
    historial dejaba de llenarse).

    Usa la sesión del DUEÑO (sin RLS) como los demás endpoints que llama
    FreeSWITCH: el CDR no trae token de usuario. La EMPRESA se deduce de
    las variables del canal que viajan dentro del payload — `nspbx_tenant_id`
    en las llamadas originadas por campañas/flujos (la fija el dialer o el
    dialplan), o el dominio en las entrantes por DID.
    """
    verificar_secreto_fs(secret)
    try:
        payload = await request.json()
    except Exception:
        raw = (await request.body()).decode(errors="replace")
        logger.warning("CDR con cuerpo no-JSON: %s", raw[:200])
        return {"ok": False}

    variables = payload.get("variables", {}) or {}
    uuid = variables.get("uuid") or payload.get("call_uuid")
    if not uuid:
        return {"ok": False}

    # Idempotencia: FreeSWITCH reintenta el POST si no recibe 200.
    existing = (await session.execute(select(CallLog).where(CallLog.uuid == uuid))).scalars().first()
    if existing:
        return {"ok": True, "duplicate": True}

    tenant_id = await _tenant_de_cdr(session, variables)
    if tenant_id is None:
        logger.warning("CDR %s sin empresa identificable; se descarta", uuid)
        return {"ok": True, "dropped": True}

    billsec = int(variables.get("billsec") or 0)
    cause = variables.get("hangup_cause") or ""
    destination = variables.get("sip_to_user") or variables.get("destination_number") or ""
    if destination in _INTERNAL_DESTS:
        destination = variables.get("sip_req_user") or destination
    if not destination:
        # En salientes NO contestadas esas variables vienen vacías y la
        # columna "Destino" del historial quedaba en blanco. El número sí
        # está en el nombre del canal ("sofia/external/3182927165").
        canal = variables.get("channel_name") or ""
        if "/" in canal:
            destination = canal.rsplit("/", 1)[-1]
        destination = destination or variables.get("sip_req_user") or ""

    # Varias claves de respaldo: en llamadas originadas por el sistema
    # (campañas, click-to-call) `caller_id_number` viene vacío y el número
    # real está en otra variable — sin esto la columna "Origen" del
    # historial salía en blanco.
    caller = (
        variables.get("caller_id_number")
        or variables.get("origination_caller_id_number")
        or variables.get("sip_from_user")
        or variables.get("ani")
    )

    call = CallLog(
        tenant_id=tenant_id,
        uuid=uuid,
        caller_number=caller,
        caller_name=variables.get("caller_id_name") or variables.get("origination_caller_id_name"),
        callee_number=destination,
        direction="inbound" if variables.get("direction") == "inbound" else "outbound",
        status=_status_from(cause, billsec),
        duration=int(variables.get("duration") or 0),
        billsec=billsec,
        hangup_cause=cause,
        recording_path=_ruta_grabacion_valida(variables.get("nspbx_recording")),
        started_at=_epoch_us_to_dt(variables.get("start_uepoch")),
        answered_at=_epoch_us_to_dt(variables.get("answer_uepoch")),
        ended_at=_epoch_us_to_dt(variables.get("end_uepoch")),
    )
    session.add(call)
    try:
        await session.commit()
    except Exception:
        await session.rollback()  # carrera con otro POST del mismo uuid
    return {"ok": True}


async def _tenant_de_cdr(session: AsyncSession, variables: dict) -> int | None:
    """A qué empresa pertenece la llamada del CDR.

    Orden de deducción: primero `nspbx_tenant_id` (la fija el dialer en
    cada campaña y el dialplan al entregar el control al voizbot); si no,
    el dominio que fijó la ruta entrante (`domain_name`); y como último
    recurso, la única empresa de la instalación. Ninguno → None, y el CDR
    se descarta: sin empresa no hay a quién asignarle el registro."""
    raw = variables.get("nspbx_tenant_id")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    dominio = variables.get("domain_name") or variables.get("sip_destination_domain")
    if dominio:
        ten = (
            await session.execute(select(Tenant).where(Tenant.sip_domain == dominio))
        ).scalar_one_or_none()
        if ten:
            return ten.id
    ten = (
        await session.execute(select(Tenant).order_by(Tenant.id).limit(1))
    ).scalar_one_or_none()
    return ten.id if ten else None


def _recording_exists(call: CallLog) -> bool:
    """Comprueba el archivo en disco, no solo que el CDR traiga una ruta.
    Las llamadas anteriores al arreglo de `record_session` quedaron con
    ruta pero sin archivo, y la interfaz ofrecía reproducir algo
    inexistente."""
    if not call.recording_path:
        return False
    return _local_recording_path(call.recording_path).exists()


def _call_out(call: CallLog) -> dict:
    return {
        "id": call.id,
        "uuid": call.uuid,
        "caller_number": call.caller_number,
        "caller_name": call.caller_name,
        "callee_number": call.callee_number,
        "direction": call.direction,
        "status": call.status,
        "duration": call.duration,
        "billsec": call.billsec,
        "hangup_cause": call.hangup_cause,
        "recording_path": call.recording_path,
        "has_recording": _recording_exists(call),
        "started_at": call.started_at,
        "answered_at": call.answered_at,
        "ended_at": call.ended_at,
    }


def _filtrar_comunes(query, direction: str | None, status: str | None, search: str | None, day: str | None):
    if direction:
        query = query.where(CallLog.direction == direction)
    if status:
        query = query.where(CallLog.status == status)
    if search:
        like = f"%{search}%"
        query = query.where((CallLog.caller_number.ilike(like)) | (CallLog.callee_number.ilike(like)))
    if day:
        # Un solo día: comparar por texto (AAAA-MM-DD) evita líos de zona
        # horaria entre construir un rango [00:00, 24:00) a mano y lo que
        # Postgres guarda — más simple y ya alcanza para este uso.
        query = query.where(func.to_char(CallLog.started_at, "YYYY-MM-DD") == day)
    return query


@router.get("/api/calls", response_model=list[CallLogOut])
async def list_calls(
    limit: int = 100,
    offset: int = 0,
    direction: str | None = None,
    status: str | None = None,
    search: str | None = None,
    # Para el panel de fechas (ver app/logs/page.tsx... digo, app/calls/page.tsx):
    # al elegir un día puntual, el límite de 100 de la vista "Todas" se
    # queda corto apenas hay una campaña activa — un solo día de pruebas
    # ya pasa de 100 llamadas y el árbol mostraba días que existían en la
    # base pero nunca llegaban a cargarse en el navegador.
    day: str | None = None,
    session: AsyncSession = Depends(get_session),
    usuario: User = _VER,
):
    query = _acotar(select(CallLog), _solo_suyas(usuario)).order_by(
        desc(CallLog.started_at), desc(CallLog.id)
    )
    query = _filtrar_comunes(query, direction, status, search, day)
    query = query.limit(min(limit, 2000) if day else min(limit, 500)).offset(offset)
    rows = (await session.execute(query)).scalars().all()
    return [_call_out(c) for c in rows]


@router.get("/api/calls/dias")
async def calls_por_dia(
    direction: str | None = None,
    status: str | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
    usuario: User = _VER,
):
    """Cuántas llamadas hay por día — independiente del límite/paginado de
    /api/calls, para que el panel Año>Mes>Día del frontend muestre TODOS
    los días que de verdad tienen datos, no solo los que entraron en la
    última página de 100/500 filas cargada."""
    clave_dia = func.to_char(CallLog.started_at, "YYYY-MM-DD")
    query = _acotar(
        select(clave_dia.label("dia"), func.count().label("total")), _solo_suyas(usuario)
    ).where(CallLog.started_at.is_not(None))
    query = _filtrar_comunes(query, direction, status, search, None).group_by(clave_dia).order_by(desc(clave_dia))
    rows = (await session.execute(query)).all()
    return [{"dia": r.dia, "total": r.total} for r in rows]


@router.get("/api/calls/serie")
async def calls_serie(
    dias: int = 7,
    session: AsyncSession = Depends(get_session),
    usuario: User = _VER,
):
    """Llamadas por día de los últimos `dias` (7-30), con días sin datos en cero,
    para la gráfica del dashboard. Mismo recorte por rol que el historial."""
    from datetime import timedelta

    from app.core.clock import now_local

    dias = max(1, min(dias, 30))
    hoy = now_local().date()
    desde = hoy - timedelta(days=dias - 1)
    clave_dia = func.to_char(CallLog.started_at, "YYYY-MM-DD")
    query = (
        _acotar(select(clave_dia.label("dia"), CallLog.status, func.count().label("n")), _solo_suyas(usuario))
        .where(CallLog.started_at >= datetime.combine(desde, datetime.min.time()))
        .group_by(clave_dia, CallLog.status)
    )
    por_dia: dict[str, dict[str, int]] = {}
    for fila in (await session.execute(query)).all():
        d = por_dia.setdefault(fila.dia, {"total": 0, "answered": 0})
        d["total"] += fila.n
        if fila.status == "answered":
            d["answered"] += fila.n
    serie = []
    for i in range(dias):
        dia = (desde + timedelta(days=i)).isoformat()
        d = por_dia.get(dia, {"total": 0, "answered": 0})
        serie.append({"dia": dia, "total": d["total"], "answered": d["answered"], "missed": d["total"] - d["answered"]})
    return serie


@router.get("/api/calls/stats")
async def call_stats(session: AsyncSession = Depends(get_session), usuario: User = _VER):
    propia = _solo_suyas(usuario)
    result = await session.execute(
        _acotar(select(CallLog.status, func.count(CallLog.id)), propia).group_by(CallLog.status)
    )
    counts = dict(result.all())
    total_min = (
        await session.execute(_acotar(select(func.coalesce(func.sum(CallLog.billsec), 0)), propia))
    ).scalar() or 0
    return {
        "total": sum(counts.values()),
        "answered": counts.get("answered", 0),
        "no_answer": counts.get("no_answer", 0),
        "busy": counts.get("busy", 0),
        "failed": counts.get("failed", 0) + counts.get("rejected", 0) + counts.get("cancelled", 0),
        "talk_minutes": round(total_min / 60, 1),
    }


@router.get("/api/calls/{call_id}", response_model=CallLogOut)
async def get_call(call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    return _call_out(await _traer(call_id, session, usuario))


@router.get("/api/calls/{call_id}/recording")
async def get_recording(call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _VER):
    """Devuelve el audio de la llamada para escuchar o descargar."""
    call = await _traer(call_id, session, usuario)
    if not call.recording_path:
        raise HTTPException(status_code=404, detail="Esta llamada no tiene grabación")

    # La ruta guardada es la que ve FreeSWITCH; el backend monta ese mismo
    # directorio en otro punto (ver volumes en docker-compose.yml).
    local = _local_recording_path(call.recording_path)
    if not local.exists():
        raise HTTPException(status_code=404, detail="El archivo de grabación ya no está en el servidor")

    fecha = call.started_at.strftime("%Y%m%d-%H%M") if call.started_at else str(call.id)
    nombre = f"llamada-{fecha}-{call.callee_number or call.caller_number or call.id}.wav"
    return FileResponse(local, media_type="audio/wav", filename=nombre)


@router.get("/api/calls/{call_id}/summary")
async def get_summary(
    call_id: int, session: AsyncSession = Depends(get_session), usuario: User = _VER
):
    """Qué pasó en la llamada, procesando la grabación.

    Se transcribe el audio con diarización (separa quién habló) y se
    resume con el modelo. Trabajar sobre la grabación —y no sobre una
    copia guardada de la conversación— tiene dos ventajas: no se duplica
    en la base algo que el audio ya contiene, y sirve para CUALQUIER
    llamada, incluidas las que nunca pasaron por el voizbot.

    El resumen sí se guarda, porque es corto y evita volver a pagar
    transcripción cada vez que alguien lo abre.
    """
    call = await _traer(call_id, session, usuario)

    uso = None
    if call.uuid:
        uso = (
            await session.execute(select(AiCallUsage).where(AiCallUsage.call_uuid == call.uuid))
        ).scalar_one_or_none()

    datos = {
        "available": True,
        "turns": uso.turns if uso else 0,
        "outcome": uso.outcome if uso else None,
        "resolved": bool(uso.resolved) if uso else False,
        # Solo el tiempo hablado. `duration` incluye el timbrado, y en una
        # llamada que nadie contestó mostraba "30s hablados" siendo 0.
        "duration_seconds": call.billsec or 0,
        "transcript": [],
        "summary": call.summary,
    }

    # Si ya se resumió antes, no se vuelve a procesar el audio: la
    # transcripción y el modelo se pagan una sola vez por llamada.
    if call.summary:
        return datos

    # Sin audio no hace falta rendirse: el CDR ya dice qué pasó. Una
    # llamada que timbró y nadie contestó no necesita que la analice un
    # modelo, y responder "no hay nada que analizar" era inútil para quien
    # solo quiere saber por qué esa llamada no prosperó.
    local = _local_recording_path(call.recording_path) if call.recording_path else None
    if local is None or not local.exists():
        falta_archivo = local is not None
        return {**datos, "summary": _resumen_sin_audio(call, falta_archivo), "from_cdr": True}

    ajustes = await ajustes_de(session)
    dg_key = (ajustes.deepgram_api_key if ajustes else None) or ""
    llm_base_url = (getattr(ajustes, "ai_llm_base_url", None) if ajustes else None) or "https://api.deepseek.com/v1"
    llm_model = (getattr(ajustes, "ai_llm_model", None) if ajustes else None) or "deepseek-chat"
    llm_key = (getattr(ajustes, "ai_llm_api_key", None) if ajustes else None) or ""
    if not dg_key or not llm_key:
        return {**datos, "available": False, "reason": "Faltan las API keys de Deepgram y del modelo de lenguaje en Ajustes."}

    try:
        turnos = await deepgram.transcribir_grabacion(local.read_bytes(), dg_key)
    except Exception as exc:
        logger.exception("No se pudo transcribir la llamada %s", call_id)
        return {**datos, "available": False, "reason": f"No se pudo transcribir la grabación: {exc}"}

    if not turnos:
        # Hay archivo pero sin voz: pasa con llamadas que se cortaron al
        # instante. Se responde con lo que dice el registro en vez de
        # dejar la ventana en blanco.
        return {
            **datos,
            "summary": _resumen_sin_audio(call),
            "from_cdr": True,
            "note": "La grabación existe pero no tiene voz reconocible.",
        }

    charla = "\n".join(f"{t['rol'].upper()}: {t['texto']}" for t in turnos)
    try:
        mensaje, _ = await llm.chat(
            llm_base_url,
            llm_model,
            llm_key,
            [
                {
                    "role": "system",
                    "content": (
                        "Resumes llamadas de un consultorio odontológico para que alguien del equipo "
                        "entienda de un vistazo qué pasó. Escribe en español, en tercera persona, "
                        "máximo tres frases. Di qué pidió la persona, qué se resolvió y si quedó algo "
                        "pendiente. La transcripción es automática y puede traer errores: si algo no se "
                        "entiende, dilo en vez de inventarlo. Los hablantes vienen numerados y no "
                        "siempre en el mismo orden; dedúcelo del contenido."
                    ),
                },
                {"role": "user", "content": charla},
            ],
            tool_choice="none",
            tools=[],
        )
        resumen = (mensaje.get("content") or "").strip()
    except Exception as exc:
        logger.exception("No se pudo resumir la llamada %s", call_id)
        return {**datos, "transcript": turnos, "reason": f"No se pudo generar el resumen: {exc}"}

    call.summary = resumen
    await session.commit()
    return {**datos, "transcript": turnos, "summary": resumen}


def _resumen_sin_audio(call: CallLog, falta_archivo: bool = False) -> str:
    """Qué pasó, contado desde el CDR, cuando no hay audio que transcribir.

    Cubre el caso más común del historial: llamadas que timbraron y nadie
    contestó. No se gasta transcripción ni modelo en algo que los datos
    de la llamada ya responden.
    """
    direccion = "Llamada saliente" if call.direction == "outbound" else "Llamada entrante"
    hacia = call.callee_number or call.caller_number
    quien = f" a {hacia}" if hacia else ""

    if call.status == "no_answer":
        return f"{direccion}{quien}: timbró {call.duration or 0} segundos y nadie contestó."
    if call.status == "busy":
        return f"{direccion}{quien}: la línea estaba ocupada."
    if call.status in ("rejected", "cancelled"):
        estado = "la rechazaron" if call.status == "rejected" else "se canceló antes de conectar"
        return f"{direccion}{quien}: {estado}."
    if call.status == "failed":
        motivo = f" ({call.hangup_cause})" if call.hangup_cause else ""
        return f"{direccion}{quien}: no se pudo completar{motivo}."

    # Contestada pero sin grabación: o duró muy poco, o colgaron durante el
    # menú, antes de que arrancara la grabación.
    if falta_archivo:
        return (
            f"{direccion}{quien}: duró {call.billsec or call.duration or 0} segundos, "
            "pero el archivo de grabación ya no está en el servidor, así que no se puede analizar."
        )
    segundos = call.billsec or call.duration or 0
    if segundos <= 10:
        return f"{direccion}{quien}: contestaron y colgaron a los {segundos} segundos, sin llegar a conversar."
    return (
        f"{direccion}{quien}: contestada, {segundos} segundos hablados. "
        "No quedó grabación, así que no hay conversación que analizar."
    )
