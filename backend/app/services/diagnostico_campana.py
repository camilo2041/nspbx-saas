"""¿Por qué esta campaña no llama? La lista de lo que tiene que estar listo
para que marque, con lo que falta y dónde se arregla.

Antes, una campaña sin troncal, con la licencia vencida, fuera de su franja
o sin agentes listos simplemente no llamaba, sin decir nada: había que
adivinar. Los mismos requisitos que revisan los motores
(services/agentes.py:revisar_campana, services/predictivo.py,
workers/dialer.py), dichos en palabras.
"""

from datetime import datetime

from sqlalchemy import func, select

from app.core.clock import now_local
from app.models import AgenteVivo, CampanaAgente, Campaign, CampaignNumber, SystemSettings, Trunk, VoiceBot
from app.services import agentes, horario_marcacion, licensing, salientes, tope_campanas

# Los que marcan solos (sin agentes listos o sin «Iniciar» no llaman).
AUTOMATICOS = ("voizbot", "progresivo", "proporcional", "predictivo")


def _item(clave: str, ok: bool, titulo: str, detalle: str = "", grave: bool = True) -> dict:
    return {"clave": clave, "ok": ok, "grave": grave, "titulo": titulo, "detalle": detalle}


async def revisar(session, campana: Campaign) -> dict:
    metodo = campana.metodo or "voizbot"
    con_agentes = metodo != "voizbot"
    items: list[dict] = []

    st = licensing.estado(await licensing.obtener(session, campana.tenant_id))
    items.append(_item(
        "licencia", st == "ok", "Licencia de la empresa al día" if st == "ok" else f"La licencia de la empresa está {st}",
        "" if st == "ok" else "Sin licencia no se puede iniciar la campaña ni entrar como agente. La renueva el operador de la plataforma en Empresas.",
    ))

    troncal = await session.get(Trunk, campana.trunk_id) if campana.trunk_id else None
    troncal_ok = troncal is not None and troncal.tenant_id == campana.tenant_id and troncal.enabled
    items.append(_item(
        "troncal", troncal_ok, f"Sale por la troncal {troncal.name}" if troncal_ok else "No tiene una troncal habilitada",
        "" if troncal_ok else "Edita la campaña y elige la troncal por la que salen las llamadas.",
    ))

    if metodo == "voizbot":
        bot = await session.get(VoiceBot, campana.voicebot_id) if campana.voicebot_id else None
        items.append(_item(
            "voizbot", bot is not None, f"Atiende el voizbot {bot.name}" if bot else "No tiene voizbot",
            "" if bot else "Edita la campaña y elige el voizbot que habla con los clientes.",
        ))

    pendientes = (await session.execute(
        select(func.count()).select_from(CampaignNumber)
        .where(CampaignNumber.campaign_id == campana.id, CampaignNumber.status == "pending")
    )).scalar_one()
    items.append(_item(
        "numeros", pendientes > 0, f"{pendientes} número(s) por llamar" if pendientes else "No hay números por llamar",
        "" if pendientes else "Agrega números (pegados o con un archivo) o usa «Reintentar» para volver a llamar los que ya pasaron.",
    ))

    # Solo la manual trabaja sin «Iniciar» (la vista previa también lo pide).
    if metodo != "manual":
        corriendo = campana.status == "running"
        items.append(_item(
            "iniciada", corriendo, "La campaña está iniciada" if corriendo else "La campaña no está iniciada",
            "" if corriendo else "Pulsa «Iniciar». Sin eso no marca aunque todo lo demás esté listo.",
        ))

    ajustes = (await session.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    ahora = now_local()
    en_franja = horario_marcacion.puede_marcar(ajustes, campana.ai_intent, ahora)
    franja = horario_marcacion.franja(ajustes, campana.ai_intent, ahora.date())
    texto_franja = f"de {franja[0].strftime('%H:%M')} a {franja[1].strftime('%H:%M')}" if franja else "hoy no se marca"
    items.append(_item(
        "franja", en_franja, f"Dentro del horario de marcación ({texto_franja})" if en_franja else f"Fuera del horario de marcación ({texto_franja})",
        "" if en_franja else "Llama sola cuando abra la franja. El horario está en Ajustes; la cobranza además tiene el de la ley.",
    ))

    politica = await salientes.politica_de(session, campana.tenant_id)
    items.append(_item(
        "salientes", not politica.bloqueo, "Las llamadas salientes están habilitadas" if not politica.bloqueo else politica.bloqueo,
        "" if not politica.bloqueo else "Revisa Ajustes → Salientes (o el cupo diario de la licencia).",
    ))

    minutos = (await tope_campanas.minutos_hoy(session, [campana.id])).get(campana.id, 0)
    _, motivo_tope = tope_campanas.disponibles(campana, ahora.date(), minutos)
    if motivo_tope:
        items.append(_item("tope", False, motivo_tope, "Sube el tope en la campaña o espera a mañana."))

    agentes_info = None
    if con_agentes:
        asignados = (await session.execute(
            select(func.count()).select_from(CampanaAgente).where(CampanaAgente.campaign_id == campana.id)
        )).scalar_one()
        items.append(_item(
            "asignados", asignados > 0, f"{asignados} agente(s) asignado(s)" if asignados else "No tiene agentes asignados",
            "" if asignados else "Más abajo, en «Agentes», marca quién trabaja esta campaña y guarda.",
        ))
        vivos = [v for v in (await session.execute(select(AgenteVivo))).scalars() if campana.id in (v.campanas or [])]
        conectados = len(vivos)
        con_audio = sum(1 for v in vivos if v.audio)
        listos = sum(1 for v in vivos if v.audio and v.estado == agentes.LISTO)
        agentes_info = {"conectados": conectados, "con_audio": con_audio, "listos": listos}
        if conectados == 0:
            items.append(_item(
                "conectados", False, "Ningún agente entró a la campaña",
                "Cada agente abre la Consola de agente, conecta el softphone, elige esta campaña y pulsa «Entrar».",
                grave=metodo in AUTOMATICOS,
            ))
        elif con_audio == 0:
            items.append(_item(
                "audio", False, f"{conectados} agente(s) dentro, pero sin audio",
                "Al entrar, la central llama a la extensión del agente y el softphone tiene que contestar. Revisa que el softphone esté conectado.",
                grave=metodo in AUTOMATICOS,
            ))
        elif metodo in AUTOMATICOS:
            items.append(_item(
                "listos", listos > 0,
                f"{listos} agente(s) listo(s) para recibir llamadas" if listos else f"{con_audio} agente(s) dentro, ninguno en «Listo»",
                "" if listos else "La campaña marca solo para agentes en «Listo»: que salgan de pausa o de la disposición.",
            ))

    if metodo == "predictivo" or metodo == "proporcional":
        items.append(_item(
            "abandono", bool(campana.audio_abandono),
            "Mensaje de abandono listo" if campana.audio_abandono else "Sin mensaje de abandono",
            "" if campana.audio_abandono else "Si contesta un cliente y no hay agente, se cuelga sin mensaje. Edita la campaña y guarda para generarlo.",
            grave=False,
        ))

    bloquean = [i for i in items if not i["ok"] and i["grave"]]
    return {
        "metodo": metodo,
        "listo": not bloquean,
        "resumen": "Todo listo: la campaña está marcando o lo hará en cuanto haya a quién." if not bloquean
        else f"No llama por: {bloquean[0]['titulo'].lower()}.",
        "items": items,
        "agentes": agentes_info,
        "revisado_en": datetime.utcnow().isoformat(),
    }
