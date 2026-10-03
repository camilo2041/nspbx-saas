"""Fase 6: webhooks firmados hacia el CRM de la empresa.

- La firma: la calcula NSPBX y la verifica el receptor (y una alterada o
  vieja no pasa).
- Solo https a destinos públicos, al guardar y otra vez al enviar.
- Los eventos salen del flujo real del agente (contesta, dispone, callback,
  no llamar), en la misma transacción.
- Entrega con reintentos y espera creciente; después «fallida»; reintento a
  mano; la prueba (ping) responde en el acto.
"""

import json
import types
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text, update

from app.core import permissions, urls
from app.core.database import async_session, sesion_de_empresa
from app.models import Disposicion, EntregaWebhook, Webhook
from app.services import agentes, integraciones

from .test_agentes import FS, _accion, _entrar, _evento, papa  # noqa: F401  (fixtures)
from .test_supervision import _cab, _usuario


@pytest.fixture
def fs(monkeypatch):
    return FS(monkeypatch)


class Receptor:
    """El CRM de mentira: guarda lo recibido y responde lo que se le pida."""

    def __init__(self, monkeypatch, secreto_de=None):
        self.recibidos: list[httpx.Request] = []
        self.codigo = 200

        def manejar(req: httpx.Request) -> httpx.Response:
            self.recibidos.append(req)
            return httpx.Response(self.codigo, text="ok" if self.codigo < 300 else "error del CRM")

        original = httpx.AsyncClient

        def cliente(**kw):
            kw.pop("follow_redirects", None)
            return original(transport=httpx.MockTransport(manejar), follow_redirects=False, **kw)

        monkeypatch.setattr(integraciones, "httpx", types.SimpleNamespace(AsyncClient=cliente, HTTPError=httpx.HTTPError))

        async def publico(url):
            return urls.validar_url_https(url)

        monkeypatch.setattr(urls, "exigir_destino_publico", publico)


@pytest.fixture
async def admin(papa):  # noqa: F811
    uid = await _usuario(papa, permissions.ADMIN, "298")
    return _cab(papa, uid, permissions.ADMIN)


async def _crear(cliente, admin, eventos=None, url="https://crm.papa.test/nspbx"):
    r = await cliente.post("/api/integraciones/webhooks", headers=admin,
                           json={"nombre": "CRM", "url": url, "eventos": eventos or list(integraciones.EVENTOS)})
    assert r.status_code == 201, r.text
    return r.json()


def test_firma_y_verificacion():
    cuerpo = '{"evento": "x"}'
    cab = integraciones.firmar("whsec_a", cuerpo, t=1_000_000)
    assert integraciones.verificar("whsec_a", cuerpo, cab, ahora=1_000_100)
    assert not integraciones.verificar("whsec_b", cuerpo, cab, ahora=1_000_100)  # otro secreto
    assert not integraciones.verificar("whsec_a", cuerpo + " ", cab, ahora=1_000_100)  # cuerpo alterado
    assert not integraciones.verificar("whsec_a", cuerpo, cab, ahora=1_000_000 + 301)  # repetido tarde
    assert not integraciones.verificar("whsec_a", cuerpo, "basura", ahora=1_000_000)


async def test_crear_listar_y_secreto(cliente, papa, admin):  # noqa: F811
    for mala in ("http://crm.papa.test/x", "https://10.0.0.5/x", "https://localhost/x", "https://user:pw@crm.test/x"):
        r = await cliente.post("/api/integraciones/webhooks", headers=admin, json={"nombre": "x", "url": mala, "eventos": ["callback.creado"]})
        assert r.status_code == 422, mala
    r = await cliente.post("/api/integraciones/webhooks", headers=admin, json={"nombre": "x", "url": "https://crm.test", "eventos": ["inventado"]})
    assert r.status_code == 422
    w = await _crear(cliente, admin)
    assert w["secreto"].startswith("whsec_")
    lista = (await cliente.get("/api/integraciones/webhooks", headers=admin)).json()
    assert lista[0]["id"] == w["id"] and "secreto" not in lista[0]
    # Guardado cifrado.
    async with async_session() as s:
        crudo = (await s.execute(text("SELECT secreto FROM webhooks WHERE id = :i"), {"i": w["id"]})).scalar_one()
    assert crudo.startswith("enc:v1:") and w["secreto"] not in crudo
    nuevo = (await cliente.post(f"/api/integraciones/webhooks/{w['id']}/rotar-secreto", headers=admin)).json()["secreto"]
    assert nuevo != w["secreto"]
    # Un asesor no entra.
    asesor = papa["cab"](papa["agentes"][0])
    assert (await cliente.get("/api/integraciones/webhooks", headers=asesor)).status_code == 403


async def test_eventos_del_flujo_del_agente(cliente, papa, fs, admin, monkeypatch):  # noqa: F811
    receptor = Receptor(monkeypatch)
    w = await _crear(cliente, admin)
    camp = papa["camp"]["manual"]
    await _entrar(papa, fs, 0, [camp])
    await _accion(papa, 0, agentes.listo)
    uuid = await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    await _evento(papa, "CHANNEL_ANSWER", uuid, agente=papa["agentes"][0])
    await _evento(papa, "CHANNEL_HANGUP_COMPLETE", uuid, agente=papa["agentes"][0])
    async with sesion_de_empresa(papa["tenant"]) as s:
        from .test_agentes import _usuario as usuario_de

        vivo = await agentes.vivo_de(s, papa["agentes"][0])
        cb = (await s.execute(select(Disposicion).where(Disposicion.codigo == "CALLBACK"))).scalar_one()
        await agentes.disponer(s, vivo, await usuario_de(s, papa["agentes"][0]), cb.id, nota="Llamar en la tarde",
                               callback_at=datetime.utcnow() + timedelta(days=1))
        await s.commit()

    async with sesion_de_empresa(papa["tenant"]) as s:
        cola = (await s.execute(select(EntregaWebhook).where(EntregaWebhook.webhook_id == w["id"]).order_by(EntregaWebhook.id))).scalars().all()
    assert [e.evento for e in cola] == ["llamada.contestada", "callback.creado", "llamada.disposicionada"]
    disp = json.loads(cola[2].payload)
    assert disp["evento"] == "llamada.disposicionada" and disp["empresa_id"] == papa["tenant"]
    assert disp["datos"]["llamada_uuid"] == uuid and disp["datos"]["disposicion"]["codigo"] == "CALLBACK"
    assert disp["datos"]["telefono"] == "3001234567" and disp["datos"]["nota"] == "Llamar en la tarde"

    # El repartidor las entrega, firmadas con el secreto del webhook.
    assert await integraciones.repartidor.ciclo() >= 3
    mias = [r for r in receptor.recibidos if r.headers["X-NSPBX-Evento"] != "ping"]
    assert len(mias) == 3
    for req in mias:
        cuerpo = req.content.decode()
        assert integraciones.verificar(w["secreto"], cuerpo, req.headers["X-NSPBX-Firma"])
        assert req.headers["X-NSPBX-Entrega"].isdigit()
    async with sesion_de_empresa(papa["tenant"]) as s:
        estados = (await s.execute(select(EntregaWebhook.estado).where(EntregaWebhook.webhook_id == w["id"]))).scalars().all()
    assert set(estados) == {"ok"}


async def test_solo_los_eventos_suscritos_y_no_llamar_del_panel(cliente, papa, admin, monkeypatch):  # noqa: F811
    Receptor(monkeypatch)
    w = await _crear(cliente, admin, eventos=["lead.no_llamar"])
    r = await cliente.post("/api/crm/no-llamar", headers=admin, json={"telefono": "3005556677", "motivo": "Lo pidió"})
    assert r.status_code == 201
    async with sesion_de_empresa(papa["tenant"]) as s:
        n = await integraciones.emitir(s, papa["tenant"], "callback.creado", {})
        cola = (await s.execute(select(EntregaWebhook).where(EntregaWebhook.webhook_id == w["id"]))).scalars().all()
    assert n == 0  # no suscrito
    assert [e.evento for e in cola] == ["lead.no_llamar"]
    assert json.loads(cola[0].payload)["datos"]["telefono"] == "3005556677"


async def test_reintentos_con_espera_y_fallida(cliente, papa, admin, monkeypatch):  # noqa: F811
    receptor = Receptor(monkeypatch)
    receptor.codigo = 500
    w = await _crear(cliente, admin)
    async with sesion_de_empresa(papa["tenant"]) as s:
        await integraciones.emitir(s, papa["tenant"], "callback.creado", {"lead_id": 1})
        await s.commit()
        eid = (await s.execute(select(EntregaWebhook.id).where(EntregaWebhook.webhook_id == w["id"]))).scalar_one()
    antes = datetime.utcnow()
    assert await integraciones.entregar(papa["tenant"], eid) == "pendiente"
    async with sesion_de_empresa(papa["tenant"]) as s:
        e = await s.get(EntregaWebhook, eid)
        wh = await s.get(Webhook, w["id"])
        assert e.intentos == 1 and e.ultimo_codigo == 500 and "error del CRM" in e.ultimo_error
        assert e.proximo_intento_at >= antes + timedelta(seconds=29)
        assert wh.fallos_seguidos == 1
    # Antes de su hora no se reintenta.
    assert await integraciones.entregar(papa["tenant"], eid) is None
    for _ in range(integraciones.MAX_INTENTOS - 1):
        estado = await integraciones.entregar(papa["tenant"], eid, forzar=True)
    assert estado == "fallida"
    assert len(receptor.recibidos) == integraciones.MAX_INTENTOS

    # A mano: vuelve a la cola y, si el CRM ya responde, llega.
    receptor.codigo = 204
    r = await cliente.post(f"/api/integraciones/entregas/{eid}/reintentar", headers=admin)
    assert r.json()["estado"] == "pendiente" and r.json()["intentos"] == 0
    assert await integraciones.entregar(papa["tenant"], eid) == "ok"
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert (await s.get(Webhook, w["id"])).fallos_seguidos == 0
    assert (await cliente.post(f"/api/integraciones/entregas/{eid}/reintentar", headers=admin)).status_code == 409


async def test_probar_y_bitacora(cliente, papa, admin, monkeypatch):  # noqa: F811
    receptor = Receptor(monkeypatch)
    w = await _crear(cliente, admin)
    r = await cliente.post(f"/api/integraciones/webhooks/{w['id']}/probar", headers=admin)
    assert r.status_code == 200 and r.json()["estado"] == "ok" and r.json()["evento"] == "ping"
    assert receptor.recibidos[-1].headers["X-NSPBX-Evento"] == "ping"
    bit = (await cliente.get(f"/api/integraciones/webhooks/{w['id']}/entregas", headers=admin)).json()
    assert bit[0]["evento"] == "ping" and bit[0]["ultimo_codigo"] == 200
    # Desactivado: no se prueba y lo encolado no sale.
    await cliente.put(f"/api/integraciones/webhooks/{w['id']}", headers=admin, json={"activo": False})
    assert (await cliente.post(f"/api/integraciones/webhooks/{w['id']}/probar", headers=admin)).status_code == 409


async def test_al_enviar_se_vuelve_a_exigir_destino_publico(papa, admin, cliente):  # noqa: F811
    """Un nombre que hoy resuelve a una IP privada (o una URL vieja) no sale."""
    w = await _crear(cliente, admin)
    async with async_session() as s:
        await s.execute(update(Webhook).where(Webhook.id == w["id"]).values(url="https://127.0.0.1/hook"))
        await s.commit()
    async with sesion_de_empresa(papa["tenant"]) as s:
        await integraciones.emitir(s, papa["tenant"], "callback.creado", {})
        await s.commit()
        eid = (await s.execute(select(EntregaWebhook.id).where(EntregaWebhook.webhook_id == w["id"]))).scalar_one()
    assert await integraciones.entregar(papa["tenant"], eid) == "pendiente"
    async with sesion_de_empresa(papa["tenant"]) as s:
        assert "URL no permitida" in (await s.get(EntregaWebhook, eid)).ultimo_error


def test_url_crm_firmada():
    url = integraciones.url_crm("https://crm.test/cliente?tel={telefono}&n={nombre}", "s3", {"telefono": "300 123", "nombre": "Ana&Co"}, t=10)
    assert url.startswith("https://crm.test/cliente?tel=300%20123&n=Ana%26Co&nspbx_ts=10&nspbx_firma=")
    base, firma = url.rsplit("&nspbx_firma=", 1)
    import hashlib
    import hmac

    assert firma == hmac.new(b"s3", base.encode(), hashlib.sha256).hexdigest()
    for mala in ("http://crm.test/x", "https://{dominio}.test/x", "https://u:p@crm.test/"):
        with pytest.raises(urls.UrlNoPermitida):
            integraciones.validar_plantilla_crm(mala)


async def test_la_consola_abre_el_crm_con_la_url_firmada(cliente, papa, fs, admin):  # noqa: F811
    camp = papa["camp"]["manual"]
    r = await cliente.put(f"/api/campaigns/{camp}", headers=admin, json={"crm_url": "http://crm.test/x"})
    assert r.status_code == 422
    r = await cliente.put(f"/api/campaigns/{camp}", headers=admin,
                          json={"crm_url": "https://crm.papa.test/ficha?tel={telefono}&lead={lead_id}&agente={agente_id}"})
    assert r.status_code == 200 and "crm_secreto" not in r.text
    secreto = (await cliente.post(f"/api/campaigns/{camp}/crm-secreto", headers=admin)).json()["secreto"]
    await _entrar(papa, fs, 0, [camp])
    await _accion(papa, 0, agentes.listo)
    await _accion(papa, 0, agentes.marcar, camp, "3001234567")
    lead = (await cliente.get("/api/agente/estado", headers=papa["cab"](papa["agentes"][0]))).json()["lead"]
    url = lead["crm_url"]
    assert url.startswith(f"https://crm.papa.test/ficha?tel=3001234567&lead={lead['id']}&agente={papa['agentes'][0]}&nspbx_ts=")
    import hashlib
    import hmac

    base, firma = url.rsplit("&nspbx_firma=", 1)
    assert firma == hmac.new(secreto.encode(), base.encode(), hashlib.sha256).hexdigest()
    # Rotar: la firma vieja ya no vale.
    nuevo = (await cliente.post(f"/api/campaigns/{camp}/crm-secreto?rotar=true", headers=admin)).json()["secreto"]
    assert nuevo != secreto
    # Sin plantilla, no hay enlace.
    await cliente.put(f"/api/campaigns/{camp}", headers=admin, json={"crm_url": ""})
    lead = (await cliente.get("/api/agente/estado", headers=papa["cab"](papa["agentes"][0]))).json()["lead"]
    assert lead["crm_url"] is None
