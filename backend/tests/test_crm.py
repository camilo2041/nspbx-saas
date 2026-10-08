"""Fase 2 del contact center: CRM, listas, reciclaje y no llamar.

- El teléfono identifica al cliente por su clave (últimos 10 dígitos).
- Los campos propios se validan; los obligatorios se exigen.
- La ficha junta el historial por cualquier teléfono del contacto, y cada
  parte solo si el usuario la puede ver por su lado.
- El marcador no toma números en no llamar, de listas pausadas ni antes de
  su próximo intento; respeta la prioridad.
- La importación de CSV crea o actualiza, reporta cada fila que no entra y
  puede cargar los contactos en una campaña.
"""

import json
import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import permissions
from app.core.database import async_session, sesion_de_empresa
from app.core.security import crear_token, hash_password
from app.models import (
    CallLog,
    Campaign,
    CampaignNumber,
    CampoContacto,
    Contacto,
    Debt,
    License,
    Lista,
    NoLlamar,
    Tenant,
    Trunk,
    User,
)
from app.services import crm, esl, hopper
from app.services.ajustes import get_or_create_settings


@pytest.fixture
async def oscar(mundo):
    """Empresa propia con troncal, una campaña quieta y usuarios por rol."""
    sufijo = uuidlib.uuid4().hex[:6]
    async with async_session() as s:
        t = Tenant(name="Oscar", slug=f"oscar{sufijo}", sip_domain=f"o{sufijo}.test", modules="voicebot,pbx", enabled=True)
        s.add(t)
        await s.flush()
        s.add(License(tenant_id=t.id, plan="enterprise", status="active"))
        ajustes = await get_or_create_settings(s, t.id)
        ajustes.campaign_hours_weekdays = ajustes.campaign_hours_saturday = "00:00-24:00"
        ajustes.campaign_sundays_holidays = True
        troncal = Trunk(tenant_id=t.id, name="principal", gateway_host="sip.oscar.test", register_enabled=False)
        s.add(troncal)
        await s.flush()
        camp = Campaign(tenant_id=t.id, name="avisos", trunk_id=troncal.id, status="idle", max_concurrency=50)
        s.add(camp)
        usuarios = {}
        for rol in (permissions.ADMIN, permissions.COORDINADOR, permissions.ASESOR):
            u = User(tenant_id=t.id, username=f"{rol}-{t.slug}", full_name=f"{rol} oscar",
                     password_hash=hash_password("clave-de-prueba"), role=rol, enabled=True)
            s.add(u)
            await s.flush()
            usuarios[rol] = u.id
        await s.commit()
    cab = {
        rol: {"Authorization": f"Bearer {crear_token(uid, rol, t.id)[0]}"} for rol, uid in usuarios.items()
    }
    return {"tenant": t.id, "campaign": camp.id, "cab": cab, "admin": cab[permissions.ADMIN]}


# --- Reglas puras ------------------------------------------------------------------


@pytest.mark.parametrize("numero", ["+57 300-123 4567", "573001234567", "3001234567", "(300) 123.4567"])
def test_la_clave_del_telefono(numero):
    assert crm.clave_telefono(numero) == "3001234567"


def test_un_numero_corto_se_compara_entero():
    assert crm.clave_telefono("1000") == "1000"
    assert crm.clave_telefono("sin dígitos") == ""


def _def(clave, tipo="texto", **kw):
    return CampoContacto(clave=clave, nombre=clave.title(), tipo=tipo, obligatorio=kw.get("obligatorio", False),
                         opciones=kw.get("opciones"))


def test_validar_campos():
    defs = {
        "plan": _def("plan", "opciones", opciones=["oro", "plata"]),
        "saldo": _def("saldo", "numero"),
        "nacimiento": _def("nacimiento", "fecha"),
        "vip": _def("vip", "si_no"),
        "sede": _def("sede", obligatorio=True),
    }
    limpio = crm.validar_campos(defs, {"plan": "oro", "saldo": "$1,500.5", "nacimiento": "1990-05-04",
                                       "vip": "Sí", "sede": " Norte "})
    assert limpio == {"plan": "oro", "saldo": 1500.5, "nacimiento": "1990-05-04", "vip": True, "sede": "Norte"}
    with pytest.raises(ValueError) as exc:
        crm.validar_campos(defs, {"plan": "bronce", "saldo": "mucho", "otro": 1})
    mensaje = str(exc.value)
    for parte in ("Plan: tiene que ser una de", "Saldo: tiene que ser un número", "«otro» no es un campo",
                  "Sede es obligatorio"):
        assert parte in mensaje
    # Al importar sobre un contacto existente se puede no exigir.
    assert crm.validar_campos(defs, {}, exigir_obligatorios=False) == {}


def test_reglas_de_reciclaje():
    assert hopper.validar_reglas({"busy": 30, "noanswer": 0}) == {"busy": 30}
    assert hopper.validar_reglas({}) is None
    for malas in ({"answered": 5}, {"busy": -1}, {"busy": 99_999_999}, {"busy": "10"}, {"busy": True}):
        with pytest.raises(ValueError):
            hopper.validar_reglas(malas)


# --- Contactos y ficha ----------------------------------------------------------------


async def test_crear_buscar_editar_y_duplicado(cliente, oscar):
    cab = oscar["admin"]
    r = await cliente.post("/api/crm/contactos", headers=cab, json={
        "nombre": "Ana Gómez", "documento": "1020", "telefono": "+57 300 555 0001",
        "telefonos": [{"numero": "6015550001", "tipo": "fijo"}], "email": "ana@x.test",
    })
    assert r.status_code == 201, r.text
    ana = r.json()
    otra = await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550001"})
    assert otra.status_code == 409 and otra.json()["detail"]["contacto_id"] == ana["id"]

    for q in ("gómez", "1020", "5550001", "ana@x"):
        hallados = (await cliente.get("/api/crm/contactos", params={"q": q}, headers=cab)).json()
        assert [c["id"] for c in hallados["contactos"]] == [ana["id"]], q

    r = await cliente.put(f"/api/crm/contactos/{ana['id']}", headers=cab, json={"ciudad": "Bogotá"})
    assert r.status_code == 200 and r.json()["ciudad"] == "Bogotá"


async def test_los_campos_propios_se_validan(cliente, oscar):
    cab = oscar["admin"]
    r = await cliente.post("/api/crm/campos", headers=cab, json={
        "clave": "plan", "nombre": "Plan", "tipo": "opciones", "opciones": ["oro", "plata"], "obligatorio": True,
    })
    assert r.status_code == 201
    assert (await cliente.post("/api/crm/campos", headers=cab, json={"clave": "plan", "nombre": "Otro"})).status_code == 409
    assert (await cliente.post("/api/crm/campos", headers=cab, json={"clave": "x", "nombre": "X", "tipo": "opciones"})).status_code == 422

    sin_plan = await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550002"})
    assert sin_plan.status_code == 422 and "Plan es obligatorio" in sin_plan.text
    malo = await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550002", "campos": {"plan": "cobre"}})
    assert malo.status_code == 422
    bueno = await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550002", "campos": {"plan": "oro"}})
    assert bueno.status_code == 201 and bueno.json()["campos"] == {"plan": "oro"}


async def test_la_ficha_junta_el_historial_por_cualquier_telefono(cliente, oscar):
    cab = oscar["admin"]
    contacto = (await cliente.post("/api/crm/contactos", headers=cab, json={
        "nombre": "Luis", "telefono": "3005550003", "telefonos": [{"numero": "6015550003"}],
    })).json()
    async with async_session() as s:
        s.add_all([
            CallLog(tenant_id=oscar["tenant"], uuid=f"u-{uuidlib.uuid4()}", caller_number="+573005550003",
                    callee_number="1000", direction="inbound", status="answered", started_at=datetime.utcnow()),
            CallLog(tenant_id=oscar["tenant"], uuid=f"u-{uuidlib.uuid4()}", caller_number="1000",
                    callee_number="6015550003", direction="outbound", status="no_answer", started_at=datetime.utcnow()),
            CallLog(tenant_id=oscar["tenant"], uuid=f"u-{uuidlib.uuid4()}", caller_number="1000",
                    callee_number="3009990000", direction="outbound", status="answered", started_at=datetime.utcnow()),
            Debt(tenant_id=oscar["tenant"], phone="573005550003", debtor_name="Luis", amount=10),
        ])
        await s.commit()
    nota = await cliente.post(f"/api/crm/contactos/{contacto['id']}/notas", headers=cab, json={"texto": "Pidió plan"})
    assert nota.status_code == 201 and nota.json()["autor"] == "admin oscar"

    f = (await cliente.get(f"/api/crm/contactos/{contacto['id']}", headers=cab)).json()
    assert len(f["llamadas"]) == 2  # la del otro número no
    assert len(f["deudas"]) == 1
    assert [n["texto"] for n in f["notas"]] == ["Pidió plan"]


async def test_la_ficha_no_muestra_lo_que_el_rol_no_puede_ver(cliente, oscar, monkeypatch):
    """Un rol con CRM pero sin «ver todas las llamadas» (personalización de
    la empresa) no ve el historial de llamadas por la ficha."""
    cab = oscar["admin"]
    contacto = (await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550004"})).json()
    async with async_session() as s:
        s.add(CallLog(tenant_id=oscar["tenant"], uuid=f"u-{uuidlib.uuid4()}", caller_number="3005550004",
                      callee_number="1000", direction="inbound", status="answered", started_at=datetime.utcnow()))
        await s.commit()
    monkeypatch.setitem(
        permissions._OVERRIDES, (oscar["tenant"], permissions.COORDINADOR),
        {permissions.LLAMADAS_VER_TODAS: False, permissions.CAMPANAS_GESTIONAR: False},
    )
    f = (await cliente.get(f"/api/crm/contactos/{contacto['id']}", headers=oscar["cab"][permissions.COORDINADOR])).json()
    assert f["secciones"]["llamadas"] is False and f["llamadas"] == []
    assert f["secciones"]["cobranza"] is False and f["campanas"] == []


async def test_el_asesor_no_entra_al_crm_todavia(cliente, oscar):
    r = await cliente.get("/api/crm/contactos", headers=oscar["cab"][permissions.ASESOR])
    assert r.status_code == 403


async def test_borrar_un_contacto_deja_sus_numeros(cliente, oscar):
    cab = oscar["admin"]
    await cliente.post(f"/api/campaigns/{oscar['campaign']}/numbers", headers=cab,
                       json={"numbers": [{"phone": "3005550005"}]})
    async with async_session() as s:
        n = (await s.execute(select(CampaignNumber).where(CampaignNumber.phone == "3005550005"))).scalar_one()
    assert (await cliente.delete(f"/api/crm/contactos/{n.contacto_id}", headers=cab)).status_code == 204
    async with async_session() as s:
        assert (await s.get(CampaignNumber, n.id)).contacto_id is None


# --- Cargas, listas y no llamar ------------------------------------------------------


async def test_cargar_numeros_crea_contactos_y_una_lista(cliente, oscar):
    cab = oscar["admin"]
    url = f"/api/campaigns/{oscar['campaign']}/numbers"
    r = await cliente.post(url, headers=cab, json={"numbers": [
        {"phone": "3005550010", "vars": {"cliente": "Marta"}}, {"phone": "3005550011"},
    ]})
    assert r.status_code == 201 and r.json()["added"] == 2 and r.json()["lista_id"]
    # Otra carga en la misma campaña: otra lista.
    r2 = (await cliente.post(url, headers=cab, json={"numbers": [{"phone": "3005550012"}]})).json()
    assert r2["lista_id"] != r.json()["lista_id"]
    # El mismo cliente en otra campaña: el mismo contacto.
    otra = (await cliente.post("/api/campaigns", headers=cab, json={"name": f"otra-{uuidlib.uuid4().hex[:4]}"})).json()
    await cliente.post(f"/api/campaigns/{otra['id']}/numbers", headers=cab, json={"numbers": [{"phone": "3005550010"}]})
    async with async_session() as s:
        filas = (await s.execute(
            select(CampaignNumber).where(CampaignNumber.phone == "3005550010").order_by(CampaignNumber.id)
        )).scalars().all()
        marta = await s.get(Contacto, filas[0].contacto_id)
    assert marta.nombre == "Marta" and len(filas) == 2 and filas[0].contacto_id == filas[1].contacto_id

    listas = (await cliente.get(f"/api/campaigns/{oscar['campaign']}/listas", headers=cab)).json()
    assert [lista["total"] for lista in listas] == [2, 1]
    r = await cliente.put(f"/api/campaigns/{oscar['campaign']}/listas/{listas[0]['id']}", headers=cab,
                          json={"activa": False, "prioridad": 3})
    assert r.status_code == 200 and r.json()["activa"] is False


async def _numeros(oscar, *telefonos, **campos) -> list[int]:
    async with async_session() as s:
        filas = [CampaignNumber(tenant_id=oscar["tenant"], campaign_id=oscar["campaign"], phone=t, **campos)
                 for t in telefonos]
        s.add_all(filas)
        await s.commit()
        return [f.id for f in filas]


async def _tomar(oscar, cuantos=10, ahora=None) -> list[str]:
    async with sesion_de_empresa(oscar["tenant"]) as s:
        camp = await s.get(Campaign, oscar["campaign"])
        tomados = await hopper.tomar(s, camp, cuantos, ahora)
        await s.commit()
        return [n.phone for n in tomados]


async def test_el_hopper_respeta_no_llamar_listas_espera_y_prioridad(cliente, oscar):
    cab = oscar["admin"]
    assert (await cliente.post("/api/crm/no-llamar", headers=cab,
                               json={"telefono": "+57 300 555 0020", "motivo": "Lo pidió"})).status_code == 201
    async with async_session() as s:
        pausada = Lista(tenant_id=oscar["tenant"], campaign_id=oscar["campaign"], nombre="pausada", activa=False)
        urgente = Lista(tenant_id=oscar["tenant"], campaign_id=oscar["campaign"], nombre="urgente", prioridad=5)
        s.add_all([pausada, urgente])
        await s.commit()
    dnc, = await _numeros(oscar, "3005550020")
    await _numeros(oscar, "3005550021", lista_id=pausada.id)
    await _numeros(oscar, "3005550022", proximo_intento_at=datetime.utcnow() + timedelta(hours=1))
    await _numeros(oscar, "3005550023")
    await _numeros(oscar, "3005550024", prioridad=2)
    await _numeros(oscar, "3005550025", lista_id=urgente.id)

    stats = (await cliente.get(f"/api/campaigns/{oscar['campaign']}/stats", headers=cab)).json()
    assert stats["en_espera"] == 2  # la lista pausada y la reprogramada

    assert await _tomar(oscar) == ["3005550025", "3005550024", "3005550023"]
    async with async_session() as s:
        n = await s.get(CampaignNumber, dnc)
    assert n.status == "no_llamar" and n.attempts == 0
    stats = (await cliente.get(f"/api/campaigns/{oscar['campaign']}/stats", headers=cab)).json()
    assert stats["no_llamar"] == 1

    # Cuando llega su hora, el reprogramado sí sale.
    assert await _tomar(oscar, ahora=datetime.utcnow() + timedelta(hours=2)) == ["3005550022"]


async def test_un_no_llamar_vencido_ya_no_bloquea(cliente, oscar):
    await cliente.post("/api/crm/no-llamar", headers=oscar["admin"], json={
        "telefono": "3005550030", "hasta": (datetime.utcnow() - timedelta(days=1)).isoformat(),
    })
    await _numeros(oscar, "3005550030")
    assert await _tomar(oscar) == ["3005550030"]


async def test_no_llamar_se_actualiza_y_se_quita(cliente, oscar):
    cab = oscar["admin"]
    a = (await cliente.post("/api/crm/no-llamar", headers=cab, json={"telefono": "3005550031", "motivo": "uno"})).json()
    b = (await cliente.post("/api/crm/no-llamar", headers=cab, json={"telefono": "573005550031", "motivo": "dos"})).json()
    assert a["id"] == b["id"] and b["motivo"] == "dos"
    listado = (await cliente.get("/api/crm/no-llamar", params={"q": "5550031"}, headers=cab)).json()
    assert listado["total"] == 1
    contacto = (await cliente.post("/api/crm/contactos", headers=cab, json={"telefono": "3005550031"})).json()
    assert contacto["no_llamar"] is True
    assert (await cliente.delete(f"/api/crm/no-llamar/{a['id']}", headers=cab)).status_code == 204
    assert (await cliente.get(f"/api/crm/contactos/{contacto['id']}", headers=cab)).json()["contacto"]["no_llamar"] is False


async def test_el_reciclaje_espera_segun_el_resultado(monkeypatch, cliente, oscar):
    from app.workers.dialer import CampaignDialer

    r = await cliente.put(f"/api/campaigns/{oscar['campaign']}", headers=oscar["admin"],
                          json={"retries": 3, "reglas_reciclaje": {"busy": 30, "noanswer": 0}})
    assert r.status_code == 200 and r.json()["reglas_reciclaje"] == {"busy": 30}
    nid, = await _numeros(oscar, "3005550040")
    assert await _tomar(oscar) == ["3005550040"]

    async def ocupado(**kw):
        raise RuntimeError("-ERR USER_BUSY")

    monkeypatch.setattr(esl, "originate", ocupado)
    async with async_session() as s:
        camp, num = await s.get(Campaign, oscar["campaign"]), await s.get(CampaignNumber, nid)
    await CampaignDialer()._dial(None, camp, num)
    async with async_session() as s:
        num = await s.get(CampaignNumber, nid)
    assert num.status == "pending"
    espera = num.proximo_intento_at - datetime.utcnow()
    assert timedelta(minutes=29) < espera <= timedelta(minutes=30)
    assert await _tomar(oscar) == []

    # «Reintentar» lo libera ya.
    async with async_session() as s:
        await s.execute(update(CampaignNumber).where(CampaignNumber.id == nid).values(status="busy"))
        await s.commit()
    assert (await cliente.post(f"/api/campaigns/{oscar['campaign']}/retry", headers=oscar["admin"])).status_code == 200
    assert await _tomar(oscar) == ["3005550040"]


# --- Importar -------------------------------------------------------------------------------


def _csv(texto: str, codificacion="utf-8"):
    return {"archivo": ("clientes.csv", texto.encode(codificacion), "text/csv")}


async def test_vista_previa_sugiere_el_mapeo(cliente, oscar):
    cab = oscar["admin"]
    await cliente.post("/api/crm/campos", headers=cab, json={"clave": "saldo", "nombre": "Saldo", "tipo": "numero"})
    r = await cliente.post("/api/crm/importar/vista-previa", headers=cab, files=_csv(
        "Nombre;Cédula;Celular;Correo;Saldo;Otra\nAna;1;3001;a@x.co;5;z\n", "cp1252"
    ))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["total_filas"] == 1
    assert datos["sugerido"] == {"Nombre": "nombre", "Cédula": "documento", "Celular": "telefono",
                                 "Correo": "email", "Saldo": "campo:saldo"}


async def test_importar_crea_actualiza_y_reporta(cliente, oscar):
    cab = oscar["admin"]
    await cliente.post("/api/crm/campos", headers=cab, json={"clave": "saldo", "nombre": "Saldo", "tipo": "numero"})
    existente = (await cliente.post("/api/crm/contactos", headers=cab, json={
        "nombre": "Viejo", "documento": "900", "telefono": "3005550050",
    })).json()
    archivo = (
        "nombre,doc,tel,tel2,mail,saldo\n"
        "Ana,100,300 555 0051,6015550051,ana@x.co,1500\n"
        "Nuevo nombre,900,3005559999,,,\n"         # mismo documento: actualiza al existente
        "Sin teléfono,101,,,,\n"
        "Correo malo,102,3005550052,,no-es-correo,\n"
        "Saldo malo,103,3005550053,,,mucho\n"
        "Ana repetida,,573005550051,,,\n"           # mismo teléfono que la fila 2
    )
    mapeo = {"nombre": "nombre", "doc": "documento", "tel": "telefono", "tel2": "telefono2",
             "mail": "email", "saldo": "campo:saldo"}
    r = await cliente.post("/api/crm/importar", headers=cab, files=_csv(archivo), data={"mapeo": json.dumps(mapeo)})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert (rep["filas"], rep["creados"], rep["actualizados"], rep["con_error"]) == (6, 1, 2, 3)
    assert [e["fila"] for e in rep["errores"]] == [4, 5, 6]
    assert "teléfono inválido" in rep["errores"][0]["motivo"]
    assert "correo inválido" in rep["errores"][1]["motivo"]
    assert "Saldo" in rep["errores"][2]["motivo"]

    async with async_session() as s:
        viejo = await s.get(Contacto, existente["id"])
        ana = (await s.execute(select(Contacto).where(Contacto.documento == "100"))).scalar_one()
    assert viejo.nombre == "Nuevo nombre"
    assert ana.nombre == "Ana repetida" and ana.campos == {"saldo": 1500.0} and ana.email == "ana@x.co"
    assert ana.telefonos == [{"numero": "6015550051", "tipo": "otro"}]


async def test_importar_a_una_campana(cliente, oscar):
    cab = oscar["admin"]
    archivo = "nombre,telefono,fecha_cita\nPedro,3005550060,\nLaura,3005550061,\n"
    r = await cliente.post(
        "/api/crm/importar", headers=cab, files=_csv(archivo),
        data={"mapeo": json.dumps({"nombre": "nombre", "telefono": "telefono", "fecha_cita": "var:fecha_cita"}),
              "campaign_id": str(oscar["campaign"]), "nombre_lista": "Octubre"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["campana"]["added"] == 2
    listas = (await cliente.get(f"/api/campaigns/{oscar['campaign']}/listas", headers=cab)).json()
    octubre = next(lista for lista in listas if lista["nombre"] == "Octubre")
    assert octubre["origen"] == "csv" and octubre["total"] == 2
    async with async_session() as s:
        n = (await s.execute(select(CampaignNumber).where(CampaignNumber.phone == "3005550060"))).scalar_one()
    assert json.loads(n.extra_data) == {"cliente": "Pedro"} and n.contacto_id


async def test_importar_a_otra_campana_o_sin_permiso(cliente, oscar, mundo):
    archivo = _csv("telefono\n3005550070\n")
    mapeo = json.dumps({"telefono": "telefono"})
    ajena = await cliente.post("/api/crm/importar", headers=oscar["admin"], files=archivo,
                               data={"mapeo": mapeo, "campaign_id": str(mundo.beta.ids["campaign"])})
    assert ajena.status_code == 404
    monkeypatch_override = {permissions.CAMPANAS_GESTIONAR: False}
    permissions._OVERRIDES[(oscar["tenant"], permissions.COORDINADOR)] = monkeypatch_override
    try:
        r = await cliente.post("/api/crm/importar", headers=oscar["cab"][permissions.COORDINADOR],
                               files=_csv("telefono\n3005550070\n"),
                               data={"mapeo": mapeo, "campaign_id": str(oscar["campaign"])})
    finally:
        permissions._OVERRIDES.pop((oscar["tenant"], permissions.COORDINADOR), None)
    assert r.status_code == 403


@pytest.mark.parametrize(
    "archivo,mapeo,mensaje",
    [
        ("", {"x": "telefono"}, "vacío"),
        ("a,b\n1,2\n", {"a": "nombre"}, "Falta indicar qué columna es el teléfono"),
        ("a,b\n1,2\n", {"z": "telefono"}, "no está en el archivo"),
        ("a,b\n1,2\n", {"a": "telefono", "b": "telefono"}, "Dos columnas"),
        ("a,b\n1,2\n", {"a": "telefono", "b": "campo:noexiste"}, "no es un campo"),
        ("a,b\n1,2\n", {"a": "telefono", "b": "var:Mal Nombre"}, "Nombre de variable inválido"),
    ],
)
async def test_errores_de_archivo_y_mapeo(cliente, oscar, archivo, mapeo, mensaje):
    r = await cliente.post("/api/crm/importar", headers=oscar["admin"], files=_csv(archivo),
                           data={"mapeo": json.dumps(mapeo)})
    assert r.status_code == 422 and mensaje in r.text


async def test_otra_empresa_no_ve_los_contactos_ni_el_no_llamar(cliente, oscar, mundo):
    await cliente.post("/api/crm/contactos", headers=oscar["admin"], json={"nombre": "Secreto", "telefono": "3005550080"})
    await cliente.post("/api/crm/no-llamar", headers=oscar["admin"], json={"telefono": "3005550080"})
    contactos = (await cliente.get("/api/crm/contactos", params={"q": "Secreto"}, headers=mundo.beta.cabeceras())).json()
    assert contactos["total"] == 0
    dnc = (await cliente.get("/api/crm/no-llamar", params={"q": "3005550080"}, headers=mundo.beta.cabeceras())).json()
    assert dnc["total"] == 0
    # Y el no llamar de una empresa no frena las campañas de otra.
    async with async_session() as s:
        assert (await s.execute(select(NoLlamar).where(NoLlamar.tenant_id == mundo.beta.id,
                                                       NoLlamar.telefono_clave == "3005550080"))).first() is None
