"""Fase 3 del contact center: agentes humanos.

FreeSWITCH se simula: se capturan los comandos (bgapi/api) y se le entregan
al motor los eventos de contestar y colgar con los uuid que él mismo fijó.
"""

import re
import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import permissions
from app.core.database import async_session, sesion_de_empresa
from app.core.security import crear_token, hash_password
from app.models import (
    AgenteVivo,
    CallLog,
    Callback,
    CampanaAgente,
    Campaign,
    CampaignNumber,
    CodigoPausa,
    Disposicion,
    EstadoAgente,
    Extension,
    License,
    Lista,
    NoLlamar,
    Nota,
    SesionAgente,
    Tenant,
    Trunk,
    User,
)
from app.services import agentes, esl, hopper
from app.services.ajustes import get_or_create_settings

from .conftest import FS_SECRET


class FS:
    """FreeSWITCH de mentira: guarda los comandos."""

    def __init__(self, monkeypatch):
        self.bgapi: list[str] = []
        self.api: list[str] = []
        self.no_existe: set[str] = set()

        async def bgapi(cmd, **_kw):
            self.bgapi.append(cmd)
            return "+OK Job-UUID: x"

        async def api(cmd, **_kw):
            self.api.append(cmd)
            uuid = cmd.split(" ", 1)[1] if cmd.startswith("uuid_kill ") else ""
            return "-ERR No such channel!" if uuid in self.no_existe else "+OK"

        monkeypatch.setattr(esl, "bgapi", bgapi)
        monkeypatch.setattr(esl, "api", api)

    def uuid(self, cmd: str) -> str:
        return re.search(r"origination_uuid=([0-9a-f-]+)", cmd).group(1)


@pytest.fixture
def fs(monkeypatch):
    return FS(monkeypatch)


@pytest.fixture
async def papa(mundo):
    """Empresa con troncal, tres campañas de agentes (manual, vista previa,
    progresivo) y dos agentes con extensión asignados a todas."""
    sufijo = uuidlib.uuid4().hex[:6]
    async with async_session() as s:
        t = Tenant(name="Papa", slug=f"papa{sufijo}", sip_domain=f"p{sufijo}.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        ajustes = await get_or_create_settings(s, t.id)
        ajustes.campaign_hours_weekdays = ajustes.campaign_hours_saturday = "00:00-24:00"
        ajustes.campaign_sundays_holidays = True
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.papa.test", register_enabled=False,
                        caller_id_number="6015550000")
        s.add(troncal)
        await s.flush()
        camps = {}
        for metodo in ("manual", "vista_previa", "progresivo"):
            c = Campaign(tenant_id=t.id, name=f"{metodo}-{sufijo}", trunk_id=troncal.id, status="idle",
                         metodo=metodo, retries=2, guion="Hola {nombre}, le habla {agente}.")
            s.add(c)
            camps[metodo] = c
        await s.flush()
        usuarios = {}
        for i, rol in enumerate((permissions.ASESOR, permissions.ASESOR)):
            ext = Extension(tenant_id=t.id, number=f"20{i}", password="clave-sip-larga-1")
            s.add(ext)
            await s.flush()
            u = User(tenant_id=t.id, username=f"agente{i}-{t.slug}", full_name=f"Agente {i}",
                     password_hash=hash_password("clave-de-prueba"), role=rol, extension_id=ext.id, enabled=True)
            s.add(u)
            await s.flush()
            usuarios[i] = u.id
            for c in camps.values():
                s.add(CampanaAgente(tenant_id=t.id, campaign_id=c.id, user_id=u.id))
        sin_ext = User(tenant_id=t.id, username=f"sinext-{t.slug}", full_name="Sin extensión",
                       password_hash=hash_password("clave-de-prueba"), role=permissions.ASESOR, enabled=True)
        s.add(sin_ext)
        await s.commit()
    return {
        "tenant": t.id,
        "slug": t.slug,
        "dominio": t.sip_domain,
        "camp": {k: v.id for k, v in camps.items()},
        "agentes": usuarios,
        "sin_ext": sin_ext.id,
        "cab": lambda uid: {"Authorization": f"Bearer {crear_token(uid, permissions.ASESOR, t.id)[0]}"},
    }


async def _usuario(s, user_id) -> User:
    return (await s.execute(select(User).where(User.id == user_id))).unique().scalar_one()


async def _entrar(papa, fs, i=0, campanas=None) -> str:
    """Entra y contesta el audio. Devuelve el uuid del audio."""
    async with sesion_de_empresa(papa["tenant"]) as s:
        u = await _usuario(s, papa["agentes"][i])
        await agentes.entrar(s, u, campanas or list(papa["camp"].values()))
        await s.commit()
    audio = fs.uuid(fs.bgapi[-1])
    await _evento(papa, "CHANNEL_ANSWER", audio, audio=papa["agentes"][i])
    return audio


async def _evento(papa, nombre, uuid, audio=None, agente=None, causa=None):
    ev = {"Event-Name": nombre, "Unique-ID": uuid, "variable_nspbx_tenant_id": str(papa["tenant"])}
    if audio:
        ev["variable_nspbx_agente_audio"] = str(audio)
    if agente:
        ev["variable_nspbx_agente_id"] = str(agente)
    if causa:
        ev["Hangup-Cause"] = causa
    await agentes.recibir(ev)


async def _accion(papa, i, fn, *args, **kw):
    async with sesion_de_empresa(papa["tenant"]) as s:
        vivo = await agentes.vivo_de(s, papa["agentes"][i])
        resultado = await fn(s, vivo, *args, **kw)
        await s.commit()
        return resultado


async def _vivo(papa, i=0) -> AgenteVivo | None:
    async with sesion_de_empresa(papa["tenant"]) as s:
        return await agentes.vivo_de(s, papa["agentes"][i], bloquear=False)


async def _disp(papa, codigo) -> int:
    async with sesion_de_empresa(papa["tenant"]) as s:
        return (await s.execute(select(Disposicion.id).where(Disposicion.codigo == codigo))).scalar_one()


async def _pausa(papa, codigo) -> int:
    async with sesion_de_empresa(papa["tenant"]) as s:
        return (await s.execute(select(CodigoPausa.id).where(CodigoPausa.codigo == codigo))).scalar_one()


async def _disponer(papa, i, codigo, **kw):
    async with sesion_de_empresa(papa["tenant"]) as s:
        vivo = await agentes.vivo_de(s, papa["agentes"][i])
        u = await _usuario(s, papa["agentes"][i])
        await agentes.disponer(s, vivo, u, await _disp(papa, codigo), **kw)
        await s.commit()


# --- Sesión -----------------------------------------------------------------------------


async def test_entrar_llama_a_la_extension_y_la_deja_en_su_sala(papa, fs):
    async with sesion_de_empresa(papa["tenant"]) as s:
        u = await _usuario(s, papa["agentes"][0])
        vivo = await agentes.entrar(s, u, [papa["camp"]["manual"]])
        await s.commit()
    cmd = fs.bgapi[-1]
    sala = f"agente_{papa['tenant']}_{papa['agentes'][0]}@nspbx_agente+flags{{endconf}}"
    assert f"user/200@{papa['dominio']}" in cmd and f"&conference({sala})" in cmd
    assert f"sip_h_X-NSPBX-Agente={vivo.token_audio}" in cmd and len(vivo.token_audio) == 32
    assert vivo.estado == agentes.PAUSA and vivo.audio is False
    # Sin audio no se puede pasar a listo.
    with pytest.raises(agentes.ErrorAgente, match="audio"):
        await _accion(papa, 0, agentes.listo)
    await _evento(papa, "CHANNEL_ANSWER", fs.uuid(cmd), audio=papa["agentes"][0])
    await _accion(papa, 0, agentes.listo)
    assert (await _vivo(papa)).estado == agentes.LISTO
    # Los catálogos de ejemplo quedaron creados.
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await s.execute(select(func.count(CodigoPausa.id)))).scalar() == len(agentes.PAUSAS_EJEMPLO)
        assert (await s.execute(select(func.count(Disposicion.id)))).scalar() == len(agentes.DISPOSICIONES_EJEMPLO)


async def test_no_se_entra_sin_extension_ni_a_campanas_ajenas(papa, fs, mundo):
    async with sesion_de_empresa(papa["tenant"]) as s:
        sin = await _usuario(s, papa["sin_ext"])
        with pytest.raises(agentes.ErrorAgente, match="extensión"):
            await agentes.entrar(s, sin, [papa["camp"]["manual"]])
        u = await _usuario(s, papa["agentes"][0])
        with pytest.raises(agentes.ErrorAgente, match="No estás asignado"):
            await agentes.entrar(s, u, [mundo.alfa.ids["campaign"]])
    assert fs.bgapi == []


# --- Marcación manual y ciclo de la llamada ---------------------------------------------------


async def test_marcar_a_mano_y_disponer_venta(papa, fs):
    await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    call = await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770001")
    cmd = fs.bgapi[-1]
    assert f"sofia/gateway/{papa['slug']}_principal/3007770001" in cmd
    assert f"origination_uuid={call}" in cmd and f"nspbx_agente_id={papa['agentes'][0]}" in cmd
    assert f"&conference(agente_{papa['tenant']}_{papa['agentes'][0]}@nspbx_agente)" in cmd
    assert "execute_on_answer=record_session" in cmd and f"llamada_{call}.wav" in cmd
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.TIMBRANDO and vivo.call_uuid == call

    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, vivo.lead_id)
        lista = await s.get(Lista, lead.lista_id)
    assert lead.contacto_id and lista.nombre == "Marcación manual" and lead.attempts == 1

    await _evento(papa, "CHANNEL_ANSWER", call, agente=papa["agentes"][0])
    assert (await _vivo(papa)).estado == agentes.EN_LLAMADA
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", call, agente=papa["agentes"][0], causa="NORMAL_CLEARING")
    assert (await _vivo(papa)).estado == agentes.DISPO
    with pytest.raises(agentes.ErrorAgente, match="disposición"):
        await _accion(papa, 0, agentes.salir)

    await _disponer(papa, 0, "VENTA", nota="Compró el plan oro")
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.LISTO and vivo.lead_id is None
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, lead.id)
        tramos = (await s.execute(select(EstadoAgente).where(EstadoAgente.sesion_id == vivo.sesion_id).order_by(EstadoAgente.id))).scalars().all()
        notas = (await s.execute(select(Nota.texto).where(Nota.contacto_id == lead.contacto_id))).scalars().all()
    assert lead.status == "done" and lead.disposicion_id == await _disp(papa, "VENTA")
    assert [t.estado for t in tramos] == ["PAUSA", "LISTO", "TIMBRANDO", "EN_LLAMADA", "DISPO", "LISTO"]
    assert all(t.fin is not None for t in tramos[:-1]) and tramos[-1].fin is None
    # La bitácora no tiene huecos: cada tramo empieza donde terminó el anterior.
    assert all(a.fin == b.inicio for a, b in zip(tramos, tramos[1:]))
    en_llamada = next(t for t in tramos if t.estado == "EN_LLAMADA")
    assert en_llamada.disposicion_id == lead.disposicion_id
    assert notas == ["Compró el plan oro"]


async def test_si_no_contestan_el_lead_se_recicla_y_vuelve_a_la_pausa(papa, fs):
    await _entrar(papa, fs)
    almuerzo = await _pausa(papa, "ALMUERZO")
    await _accion(papa, 0, agentes.pausar, almuerzo)
    call = await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770002")
    lead_id = (await _vivo(papa)).lead_id
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", call, agente=papa["agentes"][0], causa="NO_ANSWER")
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.PAUSA and vivo.codigo_pausa_id == almuerzo
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, lead_id)
    assert lead.status == "pending" and lead.last_error == "NO_ANSWER"


async def test_colgar_sin_evento_se_resuelve_igual(papa, fs):
    await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    call = await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770003")
    fs.no_existe.add(call)
    await _accion(papa, 0, agentes.colgar)
    assert f"uuid_kill {call}" in fs.api
    assert (await _vivo(papa)).estado == agentes.LISTO


async def test_lo_que_no_se_puede_marcar(papa, fs, mundo):
    await _entrar(papa, fs)
    async with async_session() as s:
        s.add(NoLlamar(tenant_id=papa["tenant"], telefono="3007770004", telefono_clave="3007770004"))
        await s.commit()
    with pytest.raises(agentes.ErrorAgente, match="no llamar"):
        await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770004")
    with pytest.raises(agentes.ErrorAgente, match="internacional|Destino|permit"):
        await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "+447700900123")
    with pytest.raises(agentes.ErrorAgente, match="Lead no encontrado"):
        await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], None, mundo.alfa.ids["campaign_number"])
    with pytest.raises(agentes.ErrorAgente, match="No estás trabajando"):
        await _accion(papa, 0, agentes.marcar, mundo.alfa.ids["campaign"], "3007770005")
    assert (await _vivo(papa)).estado == agentes.PAUSA


async def test_pausa_pedida_en_llamada_se_aplica_al_disponer(papa, fs):
    await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    call = await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770006")
    await _evento(papa, "CHANNEL_ANSWER", call, agente=papa["agentes"][0])
    descanso = await _pausa(papa, "BREAK")
    await _accion(papa, 0, agentes.pausar, descanso)
    assert (await _vivo(papa)).estado == agentes.EN_LLAMADA  # la llamada no se corta
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", call, agente=papa["agentes"][0])
    await _disponer(papa, 0, "NO_INTERESADO")
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.PAUSA and vivo.codigo_pausa_id == descanso


# --- Disposiciones ----------------------------------------------------------------------------


async def _llamada_contestada(papa, fs, telefono, i=0):
    await _accion(papa, i, agentes.listo)
    call = await _accion(papa, i, agentes.marcar, papa["camp"]["manual"], telefono)
    await _evento(papa, "CHANNEL_ANSWER", call, agente=papa["agentes"][i])
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", call, agente=papa["agentes"][i])
    return (await _vivo(papa, i)).lead_id


async def test_callback_propio_reserva_el_lead_para_el_agente(papa, fs):
    await _entrar(papa, fs)
    lead_id = await _llamada_contestada(papa, fs, "3007770010")
    cuando = datetime.utcnow() + timedelta(hours=2)
    with pytest.raises(agentes.ErrorAgente, match="cuándo"):
        await _disponer(papa, 0, "CALLBACK")
    with pytest.raises(agentes.ErrorAgente, match="futura"):
        await _disponer(papa, 0, "CALLBACK", callback_at=datetime.utcnow() - timedelta(minutes=1))
    await _disponer(papa, 0, "CALLBACK", callback_at=cuando, nota="Llamar después del almuerzo")
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, lead_id)
        cb = (await s.execute(select(Callback).where(Callback.lead_id == lead_id))).scalar_one()
        camp = await s.get(Campaign, papa["camp"]["manual"])
        assert lead.status == "pending" and lead.agente_id == papa["agentes"][0] and lead.proximo_intento_at == cuando
        assert cb.agente_id == papa["agentes"][0] and cb.estado == "pendiente"
        despues = cuando + timedelta(minutes=1)
        # Ni otro agente ni el voizbot lo toman; su dueño sí, a su hora.
        assert await hopper.tomar(s, camp, 10, despues, agente_id=papa["agentes"][1]) == []
        assert await hopper.tomar(s, camp, 10, despues) == []
        assert await hopper.tomar(s, camp, 10, cuando - timedelta(minutes=5), agente_id=papa["agentes"][0]) == []
        assert [n.id for n in await hopper.tomar(s, camp, 10, despues, agente_id=papa["agentes"][0])] == [lead_id]
        await s.rollback()


async def test_no_llamar_desde_la_disposicion(papa, fs):
    await _entrar(papa, fs)
    lead_id = await _llamada_contestada(papa, fs, "3007770011")
    await _disponer(papa, 0, "NO_LLAMAR")
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await s.get(CampaignNumber, lead_id)).status == "no_llamar"
        assert (await s.execute(select(NoLlamar).where(NoLlamar.telefono_clave == "3007770011"))).scalar_one()


async def test_no_contesta_se_recicla_y_al_agotar_intentos_cierra(papa, fs):
    await _entrar(papa, fs)
    lead_id = await _llamada_contestada(papa, fs, "3007770012")
    await _disponer(papa, 0, "NO_CONTESTA")
    async with sesion_de_empresa(papa["tenant"]) as s:
        lead = await s.get(CampaignNumber, lead_id)
        assert lead.status == "pending"
        lead.attempts = 5
        await s.commit()
    await _llamada_contestada(papa, fs, "3007770012")
    await _disponer(papa, 0, "OCUPADO")
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await s.get(CampaignNumber, lead_id)).status == "busy"


# --- Audio del agente -------------------------------------------------------------------------


async def test_si_se_cae_el_audio_pasa_a_pausa_tecnica(papa, fs):
    audio = await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", audio, audio=papa["agentes"][0])
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.PAUSA and vivo.codigo_pausa_id == await _pausa(papa, "TECNICA") and not vivo.audio
    await _accion(papa, 0, agentes.reconectar_audio)
    assert "user/200@" in fs.bgapi[-1] and fs.uuid(fs.bgapi[-1]) != audio


async def test_si_se_cae_el_audio_en_llamada_se_corta_y_se_dispone(papa, fs):
    audio = await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    call = await _accion(papa, 0, agentes.marcar, papa["camp"]["manual"], "3007770013")
    await _evento(papa, "CHANNEL_ANSWER", call, agente=papa["agentes"][0])
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", audio, audio=papa["agentes"][0])
    assert f"uuid_kill {call}" in fs.api
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", call, agente=papa["agentes"][0])
    assert (await _vivo(papa)).estado == agentes.DISPO
    await _disponer(papa, 0, "NO_INTERESADO")
    vivo = await _vivo(papa)
    assert vivo.estado == agentes.PAUSA and vivo.codigo_pausa_id == await _pausa(papa, "TECNICA")


# --- Vista previa y progresivo ------------------------------------------------------------------


async def _leads(papa, metodo, *telefonos):
    async with async_session() as s:
        await s.execute(Campaign.__table__.update().where(Campaign.id == papa["camp"][metodo]).values(status="running"))
        filas = [CampaignNumber(tenant_id=papa["tenant"], campaign_id=papa["camp"][metodo], phone=t) for t in telefonos]
        s.add_all(filas)
        await s.commit()
        return [f.id for f in filas]


async def test_vista_previa_reserva_salta_y_marca(papa, fs):
    uno, dos = await _leads(papa, "vista_previa", "3007770020", "3007770021")
    await _entrar(papa, fs)
    await _accion(papa, 0, agentes.listo)
    lead = await _accion(papa, 0, agentes.siguiente)
    assert lead.id == uno and (await _vivo(papa)).estado == agentes.PREVIA
    await _accion(papa, 0, agentes.saltar)
    async with sesion_de_empresa(papa["tenant"]) as s:
        saltado = await s.get(CampaignNumber, uno)
    assert saltado.status == "pending" and saltado.attempts == 0
    assert (await _vivo(papa)).estado == agentes.LISTO

    lead = await _accion(papa, 0, agentes.siguiente)
    with pytest.raises(agentes.ErrorAgente, match="Marca el lead"):
        await _accion(papa, 0, agentes.marcar, papa["camp"]["vista_previa"], None, dos if lead.id == uno else uno)
    await _accion(papa, 0, agentes.marcar, papa["camp"]["vista_previa"], None, lead.id)
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await s.get(CampaignNumber, lead.id)).attempts == 1  # un solo intento, no dos


async def test_progresivo_marca_a_cada_agente_listo(papa, fs):
    await _leads(papa, "progresivo", "3007770030", "3007770031", "3007770032")
    await _entrar(papa, fs, 0, [papa["camp"]["progresivo"]])
    await _entrar(papa, fs, 1, [papa["camp"]["progresivo"]])
    await _accion(papa, 0, agentes.listo)  # el 1 sigue en pausa
    antes = len(fs.bgapi)
    assert await agentes.motor.ciclo() == 1
    assert len(fs.bgapi) == antes + 1
    vivo = await _vivo(papa, 0)
    assert vivo.estado == agentes.TIMBRANDO and vivo.telefono == "3007770030"
    assert (await _vivo(papa, 1)).estado == agentes.PAUSA
    # Ya ocupado: la vuelta siguiente no le marca otro.
    assert await agentes.motor.ciclo() == 0


async def test_el_marcador_del_voizbot_no_toca_campanas_de_agentes(papa, fs, monkeypatch):
    from app.workers import dialer

    await _leads(papa, "progresivo", "3007770040")
    tomados = []

    async def estado():
        return {"current_sessions": 0}

    async def dial(self, session, campaign, number):
        tomados.append(campaign.id)

    monkeypatch.setattr(esl, "status", estado)
    monkeypatch.setattr(dialer.CampaignDialer, "_dial", dial)
    await dialer.CampaignDialer()._process_once()
    assert papa["camp"]["progresivo"] not in tomados


# --- Salir, CDR y la API ---------------------------------------------------------------------------


async def test_salir_cierra_la_sesion_y_cuelga_el_audio(papa, fs):
    audio = await _entrar(papa, fs)
    sesion_id = (await _vivo(papa)).sesion_id
    await _accion(papa, 0, agentes.salir)
    assert f"uuid_kill {audio}" in fs.api
    assert await _vivo(papa) is None
    async with sesion_de_empresa(papa["tenant"]) as s:
        sesion = await s.get(SesionAgente, sesion_id)
        abiertos = (await s.execute(select(func.count()).where(EstadoAgente.sesion_id == sesion_id, EstadoAgente.fin.is_(None)))).scalar()
    assert sesion.fin is not None and sesion.motivo_fin == "normal" and abiertos == 0


async def test_al_reiniciar_se_cierran_las_sesiones(papa, fs):
    await _entrar(papa, fs)
    await agentes.cerrar_todas()
    assert await _vivo(papa) is None


async def test_el_cdr_guarda_agente_lead_y_disposicion(cliente, papa, fs, mundo):
    await _entrar(papa, fs)
    lead_id = await _llamada_contestada(papa, fs, "3007770050")
    call = (await _vivo(papa)).call_uuid
    await _disponer(papa, 0, "VENTA")

    async def cdr(u, agente):
        await cliente.post(f"/fs/cdr/{FS_SECRET}", json={"variables": {
            "uuid": u, "nspbx_tenant_id": str(papa["tenant"]), "nspbx_agente_id": str(agente),
            "nspbx_lead_id": str(lead_id), "direction": "outbound", "billsec": "30", "hangup_cause": "NORMAL_CLEARING",
        }})
        async with async_session() as s:
            return (await s.execute(select(CallLog).where(CallLog.uuid == u))).scalar_one()

    fila = await cdr(call, papa["agentes"][0])
    assert (fila.agente_id, fila.lead_id, fila.disposicion_id) == (papa["agentes"][0], lead_id, await _disp(papa, "VENTA"))
    # Un agente de otra empresa en la variable: no se atribuye.
    ajeno = await cdr(f"x-{uuidlib.uuid4()}", mundo.alfa.usuarios["asesor"])
    assert ajeno.agente_id is None and ajeno.lead_id is None


async def test_la_api_del_agente(cliente, papa, fs):
    cab = papa["cab"](papa["agentes"][0])
    r = await cliente.get("/api/agente/estado", headers=cab)
    assert r.status_code == 200 and r.json()["agente"] is None
    assert {c["id"] for c in r.json()["campanas"]} == set(papa["camp"].values())
    r = await cliente.post("/api/agente/entrar", headers=cab, json={"campanas": [papa["camp"]["manual"]]})
    assert r.status_code == 200 and r.json()["agente"]["estado"] == "PAUSA"
    assert r.json()["agente"]["token_audio"]
    assert (await cliente.post("/api/agente/listo", headers=cab)).status_code == 409  # sin audio
    await _evento(papa, "CHANNEL_ANSWER", fs.uuid(fs.bgapi[-1]), audio=papa["agentes"][0])
    assert (await cliente.post("/api/agente/listo", headers=cab)).json()["agente"]["estado"] == "LISTO"
    r = await cliente.post("/api/agente/marcar", headers=cab, json={"campaign_id": papa["camp"]["manual"], "telefono": "300 777 0060"})
    assert r.status_code == 200, r.text
    estado = r.json()
    assert estado["agente"]["estado"] == "TIMBRANDO" and estado["lead"]["telefono"] == "3007770060"
    assert estado["lead"]["guion"] == "Hola {nombre}, le habla Agente 0."  # sin nombre todavía: queda visible
    assert (await cliente.post("/api/agente/salir", headers=cab)).status_code == 409


async def test_otro_agente_no_llama_un_callback_ajeno(cliente, papa, fs):
    await _entrar(papa, fs)
    await _llamada_contestada(papa, fs, "3007770070")
    await _disponer(papa, 0, "CALLBACK", callback_at=datetime.utcnow() + timedelta(hours=1))
    async with sesion_de_empresa(papa["tenant"]) as s:
        cb = (await s.execute(select(Callback.id).order_by(Callback.id.desc()).limit(1))).scalar_one()
    r = await cliente.post(f"/api/agente/callbacks/{cb}/llamar", headers=papa["cab"](papa["agentes"][1]))
    assert r.status_code == 404
    otro = (await cliente.get("/api/agente/estado", headers=papa["cab"](papa["agentes"][1]))).json()
    assert otro["callbacks"] == []
    mio = (await cliente.get("/api/agente/estado", headers=papa["cab"](papa["agentes"][0]))).json()
    assert [c["id"] for c in mio["callbacks"]] == [cb] and mio["callbacks"][0]["propio"] is True


async def test_asignar_agentes_y_catalogos(cliente, papa, mundo):
    cab = mundo.alfa.cabeceras()
    camp = mundo.alfa.ids["campaign"]
    r = await cliente.get(f"/api/campaigns/{camp}/agentes", headers=cab)
    assert r.status_code == 200
    asesor = next(a for a in r.json() if a["username"].startswith("asesor-"))
    r = await cliente.put(f"/api/campaigns/{camp}/agentes", headers=cab, json={"user_ids": [asesor["id"]]})
    assert [a["id"] for a in r.json() if a["asignado"]] == [asesor["id"]]
    ajeno = await cliente.put(f"/api/campaigns/{camp}/agentes", headers=cab, json={"user_ids": [papa["agentes"][0]]})
    assert ajeno.status_code == 400
    await cliente.put(f"/api/campaigns/{camp}/agentes", headers=cab, json={"user_ids": []})

    pausas = (await cliente.get("/api/contact-center/pausas", headers=cab)).json()
    assert any(p["codigo"] == "BREAK" for p in pausas)
    dup = await cliente.post("/api/contact-center/pausas", headers=cab, json={"codigo": "BREAK", "nombre": "Otro"})
    assert dup.status_code == 409
    mala = await cliente.post("/api/contact-center/disposiciones", headers=cab,
                              json={"codigo": "X", "nombre": "X", "categoria": "inventada"})
    assert mala.status_code == 422
    r = await cliente.get("/api/contact-center/disposiciones", headers=cab)
    assert r.status_code == 200
    assert (await cliente.get("/api/contact-center/pausas", headers=mundo.alfa.cabeceras(permissions.ASESOR))).status_code == 403


async def test_sin_softphone_conectado_lo_dice_en_vez_de_quedar_sin_audio(papa, fs, monkeypatch):  # noqa: F811
    async def api(cmd, **_kw):
        fs.api.append(cmd)
        return "error/user_not_registered" if cmd.startswith("sofia_contact ") else "+OK"

    monkeypatch.setattr(esl, "api", api)
    with pytest.raises(agentes.ErrorAgente, match="no está conectada"):
        await _entrar(papa, fs, 0)
    assert not fs.bgapi  # no se originó nada
