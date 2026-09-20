"""Simulador de voizbots: conversar con un bot como lo haría un cliente, sin llamar.

- Bots con menú (IVR / flujo visual): se recorre el flujo tecla a tecla.
- Bots de IA: se conversa por texto con el MISMO prompt que usa la llamada real
  (`ai_agent._prompt_con_fecha`), pero las herramientas son SIMULADAS: consultar
  horarios lee la agenda real, todo lo demás responde "como si" funcionara y NO
  escribe nada. Así se puede probar un guion sin mover citas ni registrar promesas.
"""
import json
import logging
import re
from datetime import datetime, timedelta

from app.core.clock import fecha_en_palabras, now_local
from app.services import ai_intents, flow_engine, llm
from app.services.appointments import (
    available_slots,
    find_next_appointment,
    business_hours_error,
    is_slot_free,
    parse_date,
    parse_time,
)

logger = logging.getLogger(__name__)

MAX_MENSAJES = 24
MAX_CHARS = 600
MAX_VUELTAS_HERRAMIENTAS = 4
TECLAS = set("0123456789*#")


# ---------------------------------------------------------------- IVR ----

def _texto_nodo(nodo: dict) -> str:
    d = nodo.get("data") or {}
    texto = (d.get("tts_text") or "").strip()
    if texto:
        return texto[:MAX_CHARS]
    if d.get("audio_path"):
        return f"🔊 (audio grabado: {d.get('label') or nodo.get('id')})"
    return f"({d.get('label') or nodo.get('id')})"


def paso_ivr(bot, nodo_id: str | None, tecla: str | None) -> dict:
    """Un paso del recorrido del menú. `nodo_id` None = empezar."""
    flow = flow_engine.parse_flow(bot.flow_json) or flow_engine.legacy_flow_from_bot(bot)
    nodos = {str(n["id"]): n for n in flow["nodes"]}
    if not nodos:
        return {"modo": "ivr", "fin": True, "texto": "Este bot no tiene ningún menú configurado.", "opciones": []}

    def opciones_de(nid: str) -> list[dict]:
        salida = []
        for e in flow["edges"]:
            if str(e.get("source")) != nid:
                continue
            t = str(e.get("sourceHandle", "")).strip()
            destino = nodos.get(str(e.get("target")))
            if t in TECLAS and destino:
                etiqueta = (destino.get("data") or {}).get("label") or destino.get("type") or "destino"
                salida.append({"tecla": t, "etiqueta": str(etiqueta)[:60]})
        return sorted(salida, key=lambda o: o["tecla"])

    def mostrar(nodo: dict) -> dict:
        nid = str(nodo["id"])
        ops = opciones_de(nid)
        return {"modo": "ivr", "nodo": nid, "texto": _texto_nodo(nodo), "opciones": ops, "fin": not ops}

    if nodo_id is None:
        inicio = flow_engine._start_node(flow)
        return mostrar(inicio) if inicio else {"modo": "ivr", "fin": True, "texto": "Menú vacío.", "opciones": []}

    actual = nodos.get(str(nodo_id))
    if not actual:
        return {"modo": "ivr", "fin": True, "texto": "El menú cambió mientras probabas; empieza de nuevo.", "opciones": []}
    if not tecla or tecla not in TECLAS:
        return {**mostrar(actual), "nota": "Tecla no válida."}

    for e in flow["edges"]:
        if str(e.get("source")) == str(nodo_id) and str(e.get("sourceHandle", "")).strip() == tecla:
            destino = nodos.get(str(e.get("target")))
            if not destino:
                break
            tipo = destino.get("type", "menu")
            d = destino.get("data") or {}
            if tipo == "menu":
                return mostrar(destino)
            if tipo == "hangup":
                return {"modo": "ivr", "fin": True, "texto": _texto_nodo(destino), "opciones": [], "nota": "La llamada se cuelga."}
            if tipo == "transfer":
                ext = str(d.get("extension", "")).strip()
                if ext == "ai_agent":
                    return {
                        "modo": "ia",
                        "fin": False,
                        "texto": "Pasa con la asistente de IA.",
                        "intencion": str(d.get("intent") or "general"),
                        "opciones": [],
                        "nota": "Desde aquí conversas con la IA (escribe tu mensaje).",
                    }
                return {"modo": "ivr", "fin": True, "texto": f"Se transfiere la llamada a la extensión {ext or '(sin definir)'}.", "opciones": []}
    return {**mostrar(actual), "nota": f"La tecla {tecla} no tiene destino: la persona oiría «opción inválida»."}


# ----------------------------------------------------------------- IA ----

_TEL_RE = re.compile(r"[^0-9+]")


def telefono_simulado(valor: str | None) -> str:
    return _TEL_RE.sub("", valor or "")[:30]


async def datos_reales(session, tenant_id: int | None, telefono: str, intencion_key: str):
    """La cita o la deuda REALES de ese teléfono, buscadas igual que en una llamada."""
    from app.services.ai_agent import _buscar_deuda  # import tardío: arrastra el servidor ESL

    if not telefono or tenant_id is None:
        return None, None
    intencion = ai_intents.obtener(intencion_key)
    if intencion.key == "cobranza":
        return None, await _buscar_deuda(session, telefono, tenant_id)
    return await find_next_appointment(session, telefono, tenant_id=tenant_id), None


def resumen_datos(telefono: str, cita, deuda, intencion: ai_intents.Intencion) -> dict:
    """Lo que el bot "sabe" de quien llama, para mostrarlo en la prueba."""
    if not telefono:
        return {"telefono": "", "modo": "ficticio", "detalle": "Sin número: se usa una persona de prueba con una cita ficticia."}
    if cita:
        cuando = f"{fecha_en_palabras(cita.appointment_date.date())} a las {cita.appointment_date.strftime('%H:%M')}"
        return {"telefono": telefono, "modo": "real", "tipo": "cita", "detalle": f"Cita de {cita.patient_name}: {cuando}."}
    if deuda:
        monto = f"{int(deuda.amount):,}".replace(",", ".")
        return {"telefono": telefono, "modo": "real", "tipo": "deuda", "detalle": f"Deuda de {deuda.debtor_name}: {monto} pesos."}
    faltante = "deuda" if intencion.key == "cobranza" else "cita"
    return {
        "telefono": telefono,
        "modo": "real",
        "tipo": "nada",
        "detalle": f"No hay ninguna {faltante} para {telefono} en esta empresa: el bot respondería como si no la encontrara.",
    }


def _sistema_prueba(intencion_key: str, telefono: str, cita, deuda) -> tuple[str, ai_intents.Intencion]:
    from app.services.ai_agent import _bloque_cita, _bloque_deuda, _prompt_con_fecha  # import tardío

    intencion = ai_intents.obtener(intencion_key)
    texto = _prompt_con_fecha(intencion)
    if not telefono:
        manana = (now_local() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        texto += (
            "\n\nMODO PRUEBA (simulación SIN número): quien escribe es una persona de prueba, ya identificada, "
            "llamada 'Persona de Prueba', con una cita de prueba "
            f"para el {fecha_en_palabras(manana.date())} a las 10:00. No le pidas el nombre para verificarla. "
            "Las herramientas son simuladas: úsalas igual que en una llamada real."
        )
        return texto, intencion
    # Con número: el MISMO contexto que en una llamada entrante real (datos reales y confidenciales).
    texto += "\n\nMODO PRUEBA (simulación): las herramientas que modifican datos son simuladas y no escriben nada."
    if deuda:
        texto += _bloque_deuda(deuda)
    elif cita:
        texto += _bloque_cita(cita, False)
    elif intencion.requiere_cita:
        texto += "\n\nNo hay ninguna cita agendada para el número de quien llama: díselo con amabilidad y despídete."
    elif intencion.key == "cobranza":
        texto += "\n\nNo hay ninguna deuda registrada para el número de quien llama: díselo con amabilidad y despídete."
    return texto, intencion


async def _herramienta_simulada(session, nombre: str, args: dict, tenant_id: int | None, telefono: str) -> tuple[str, dict]:
    """(texto para el modelo, acción para mostrar). No escribe en la base."""
    from app.services.ai_agent import _PIDE_NOMBRE, _buscar_cita, _sin_verificar  # import tardío

    accion = {"herramienta": nombre, "argumentos": args, "simulada": True}
    try:
        if nombre == "consultar_disponibilidad":
            d = parse_date(args["date"])
            slots = await available_slots(session, d, tenant_id)
            cuando = fecha_en_palabras(d)
            resultado = f"Horarios libres el {cuando}: {', '.join(slots)}" if slots else f"No hay horarios libres el {cuando}."
            accion["resultado"] = resultado
            accion["simulada"] = False  # lectura real de la agenda
            return resultado, accion
        if nombre == "agendar_cita":
            inicio = datetime.combine(parse_date(args["date"]), parse_time(args["time"]))
            motivo = business_hours_error(inicio, 30)
            if motivo:
                resultado = f"{motivo} Ofrécele otro horario."
            elif not await is_slot_free(session, inicio, 30, tenant_id):
                resultado = "Ese horario ya está ocupado."
            else:
                resultado = f"Cita agendada para el {fecha_en_palabras(inicio.date())} a las {inicio.strftime('%H:%M')}."
        elif nombre in ("confirmar_cita", "cancelar_cita", "reagendar_cita"):
            # Sobre la cita REAL de ese número, con la misma verificación de identidad que en una llamada.
            appt = await _buscar_cita(session, telefono, None, tenant_id) if telefono else None
            if telefono and not appt:
                resultado = "No encontré una cita para ese número."
            elif appt and _sin_verificar(appt, args, None):
                resultado = _PIDE_NOMBRE
            else:
                cuando = ""
                if appt:
                    cuando = f" del {fecha_en_palabras(appt.appointment_date.date())} a las {appt.appointment_date.strftime('%H:%M')}"
                if nombre == "confirmar_cita":
                    resultado = f"Cita{cuando} confirmada por el paciente."
                elif nombre == "cancelar_cita":
                    resultado = f"Cita{cuando} cancelada."
                else:
                    nuevo = datetime.combine(parse_date(args["new_date"]), parse_time(args["new_time"]))
                    motivo = business_hours_error(nuevo, 30)
                    if motivo:
                        resultado = f"{motivo} Ofrécele otro horario."
                    elif not await is_slot_free(session, nuevo, 30, tenant_id):
                        resultado = "Ese nuevo horario ya está ocupado."
                    else:
                        resultado = f"Cita{cuando} reagendada para el {fecha_en_palabras(nuevo.date())} a las {nuevo.strftime('%H:%M')}."
        elif nombre == "registrar_promesa":
            resultado = f"Promesa registrada: {args.get('tipo', 'completo')} por {args.get('monto', '?')} pesos para el {args.get('fecha', '?')}."
        elif nombre == "terminar_llamada":
            resultado = "Llamada finalizada."
        else:
            resultado = "Herramienta no disponible en la simulación."
    except Exception as exc:  # fecha u hora mal formada, etc.: se lo dice al modelo como haría la herramienta real
        resultado = f"No se pudo ejecutar: {exc}"
    accion["resultado"] = resultado
    return resultado, accion


async def turno_ia(
    session, ajustes, tenant_id: int | None, mensajes: list[dict], intencion_key: str, telefono: str = ""
) -> dict:
    clave = (getattr(ajustes, "ai_llm_api_key", None) if ajustes else None) or ""
    if not clave:
        raise ValueError("Falta configurar la API key del modelo de lenguaje en Ajustes")
    base = (getattr(ajustes, "ai_llm_base_url", None) or "https://api.deepseek.com/v1")
    modelo = getattr(ajustes, "ai_llm_model", None) or "deepseek-chat"

    telefono = telefono_simulado(telefono)
    cita, deuda = await datos_reales(session, tenant_id, telefono, intencion_key)
    sistema, intencion = _sistema_prueba(intencion_key, telefono, cita, deuda)
    conversacion = [{"role": "system", "content": sistema}] + mensajes
    herramientas = llm.tools_para(intencion.tools)
    acciones: list[dict] = []
    terminada = False
    texto = ""

    for _ in range(MAX_VUELTAS_HERRAMIENTAS):
        msg, _uso = await llm.chat(base, modelo, clave, conversacion, tools=herramientas)
        llamadas = llm.parse_tool_calls(msg)
        texto = (msg.get("content") or "").strip() or texto
        if not llamadas:
            break
        conversacion.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})
        for call_id, nombre, args in llamadas:
            resultado, accion = await _herramienta_simulada(session, nombre, args, tenant_id, telefono)
            acciones.append(accion)
            if nombre == "terminar_llamada":
                terminada = True
            conversacion.append({"role": "tool", "tool_call_id": call_id, "content": resultado})
        if terminada:
            break
    else:
        # Demasiadas vueltas de herramientas: se fuerza una respuesta en texto.
        msg, _uso = await llm.chat(base, modelo, clave, conversacion, tool_choice="none", tools=herramientas)
        texto = (msg.get("content") or "").strip() or texto

    return {
        "modo": "ia",
        "reply": texto[:2000] or "(el bot no dijo nada)",
        "terminada": terminada,
        "acciones": acciones,
        "intencion": intencion.key,
        "datos": resumen_datos(telefono, cita, deuda, intencion),
    }
