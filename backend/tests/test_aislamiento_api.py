"""I1 e I3 en la API: un administrador de alfa ataca cada recurso de beta.

Las rutas no se listan a mano: se recorren TODAS las de la aplicación que
llevan un identificador en la URL. Una ruta nueva entra sola a la prueba,
y si su parámetro no se sabe a qué recurso apunta, la prueba falla y
obliga a declararlo (o a justificar por qué queda fuera).

Para cada ataque se exige:
  - que responda 404 o 403 (ni 2xx, ni 5xx, ni un 422 que tape la prueba),
  - que la respuesta no contenga ningún dato de beta,
y al final, que las filas de beta en la base sean idénticas a las de antes.
Esta última comprobación no depende de qué código devolvió cada endpoint.
"""

import re

import pytest

from app.core import permissions

from .conftest import foto_de_empresa
from .rutas import rutas_api

# Parámetro de la URL -> recurso de conftest.Empresa.ids
_RECURSO_POR_PARAMETRO = {
    "extension_id": "extension",
    "trunk_id": "trunk",
    "bot_id": "voicebot",
    "queue_id": "queue",
    "campaign_id": "campaign",
    "number_id": "campaign_number",
    "call_id": "call",
    "appointment_id": "appointment",
    "debt_id": "debt",
    "promise_id": "promise",
    "user_id": "user",
    "version_id": "voicebot_version",
    "key_id": "api_key",
    "contacto_id": "contacto",
    "lista_id": "lista",
    "campo_id": "campo_contacto",
    "no_llamar_id": "no_llamar",
    "pausa_id": "codigo_pausa",
    "disposicion_id": "disposicion",
    "callback_id": "callback",
    "token_id": "token_wallboard",
    "webhook_id": "webhook",
    "entrega_id": "entrega_webhook",
    "programado_id": "reporte_programado",
    "mensaje_id": "mensaje_buzon",
    "devolucion_id": "devolucion",
    "fecha_id": "fecha_especial",
    "evaluacion_id": "evaluacion",
}

# Rutas con parámetro que NO son recursos de una empresa. Cada una dice por
# qué y dónde se prueba en cambio.
_FUERA_DE_ESTA_PRUEBA = {
    "/api/plataforma/instalaciones/{inst_id}": "solo plataforma — test_instalaciones.py",
    "/api/plataforma/instalaciones/{inst_id}/codigo": "solo plataforma — test_instalaciones.py",
    "/api/plataforma/instalaciones/{inst_id}/suspender": "solo plataforma — test_instalaciones.py",
    "/api/plataforma/instalaciones/{inst_id}/reactivar": "solo plataforma — test_instalaciones.py",
    "/api/plataforma/instalaciones/{inst_id}/revocar": "solo plataforma — test_instalaciones.py",
    "/api/plataforma/nodos/{nodo_id}": "solo plataforma — test_nodos.py",
    "/api/plataforma/nodos/{nodo_id}/probar": "solo plataforma — test_nodos.py",
    "/api/plataforma/nodos/empresas/{tenant_id}": "solo plataforma — test_nodos.py",
    "/api/plataforma/sin-ruta/{numero_id}": "solo plataforma — test_fase_f.py",
    "/api/plataforma/verificacion/{verif_id}/comprobar": "solo plataforma — test_fase_j.py",
    "/api/plataforma/verificacion/{verif_id}/resultado": "solo plataforma — test_fase_j.py",
    "/api/plataforma/errores/{error_id}/resuelto": "solo plataforma — test_fase_j.py",
    "/api/plataforma/preguntas-sin-guia/{pregunta_id}": "solo plataforma — test_fase_j.py",
    "/api/tenants/{tenant_id}": "solo plataforma — test_alcance.py",
    "/api/tenants/{tenant_id}/licencia": "solo plataforma — test_alcance.py",
    "/api/tenants/{tenant_id}/salientes/colgar": "solo plataforma — test_emergencia.py",
    "/api/auth/dispositivo/{platform}": "actúa sobre el propio usuario, no recibe ids",
    "/api/auth/sesiones/{sesion_id}": "solo las sesiones del propio usuario — test_sesiones_abiertas.py",
    "/api/tenants/{tenant_id}/cerrar-sesiones": "solo plataforma — test_alcance.py",
    "/api/webcall/session/{username}/end": "widget anónimo con credencial temporal propia",
    "/api/v1/campanas/{campaign_id}/numeros": "API pública, entra con clave de API — test_api_v1.py",
    "/api/v1/campanas/{campaign_id}/leads": "API pública, entra con clave de API — test_api_v1.py",
    "/api/v1/leads/{lead_id}": "API pública, entra con clave de API — test_api_v1.py",
}

# Cuerpos válidos para que la petición pase la validación y llegue a buscar
# el recurso. Sin esto un 422 taparía un endpoint sin filtro. Cambian algo
# visible en la foto de la base pero inofensivo para el resto de pruebas
# (no desactivan troncales ni rutas que usa el dialplan).
_CUERPOS = {
    ("PUT", "/api/calls/{call_id}/conservar"): {"conservar": True},
    ("PUT", "/api/extensions/{extension_id}"): {"voicemail": False},
    ("PUT", "/api/trunks/{trunk_id}"): {"caller_id_number": "3001112233"},
    ("PUT", "/api/voicebots/{bot_id}"): {"welcome_message": "Pisado"},
    ("PUT", "/api/voicebots/{bot_id}/flow"): {"nodes": [], "edges": []},
    ("PUT", "/api/queues/{queue_id}"): {"wrap_up_time": 11},
    ("PUT", "/api/campaigns/{campaign_id}"): {"message_template": "Pisado"},
    ("PUT", "/api/campaigns/{campaign_id}/numbers/{number_id}"): {"phone": "3001234567"},
    ("POST", "/api/campaigns/{campaign_id}/numbers"): {"numbers": [{"phone": "3001234567"}]},
    ("PUT", "/api/inbound-routes/{route_id}"): {"priority": 11},
    ("PUT", "/api/outbound-routes/{route_id}"): {"priority": 11},
    ("PUT", "/api/appointments/{appointment_id}"): {"notes": "Pisado"},
    ("PUT", "/api/cobranza/debts/{debt_id}"): {"notes": "Pisado"},
    ("PUT", "/api/cobranza/promises/{promise_id}"): {"notes": "Pisado"},
    ("PUT", "/api/users/{user_id}"): {"full_name": "Pisado"},
    ("PUT", "/api/campaigns/{campaign_id}/listas/{lista_id}"): {"prioridad": 5},
    ("PUT", "/api/crm/contactos/{contacto_id}"): {"email": "pisado@x.test"},
    ("PUT", "/api/crm/campos/{campo_id}"): {"nombre": "Pisado"},
    ("PUT", "/api/contact-center/pausas/{pausa_id}"): {"orden": 3},
    ("PUT", "/api/campaigns/{campaign_id}/agentes"): {"user_ids": []},
    ("PUT", "/api/contact-center/disposiciones/{disposicion_id}"): {"orden": 3},
    ("POST", "/api/crm/contactos/{contacto_id}/notas"): {"texto": "Pisado"},
    ("POST", "/api/extensions/{extension_id}/call"): {"destination": "1001"},
    ("POST", "/api/voicebots/{bot_id}/tts"): {"text": "Hola", "voice": "es-CO-SalomeNeural"},
    ("POST", "/api/voicebots/{bot_id}/flow/nodes/{node_id}/tts"): {"text": "Hola", "voice": "es-CO-SalomeNeural"},
    ("POST", "/api/voicebots/{bot_id}/probar"): {"mensaje": "hola"},
    ("PUT", "/api/supervision/campanas/{campaign_id}/nivel"): {"abandono_objetivo": 3.0},
    ("POST", "/api/supervision/agentes/{user_id}/monitorear"): {"modo": "escuchar"},
    ("POST", "/api/supervision/agentes/{user_id}/pausa"): {"codigo_pausa_id": None},
    ("POST", "/api/supervision/agentes/{user_id}/sacar"): {"cortar_llamada": False},
    ("PUT", "/api/integraciones/webhooks/{webhook_id}"): {"nombre": "Pisado"},
    ("PUT", "/api/reportes/programados/{programado_id}"): {"nombre": "Pisado"},
    ("PUT", "/api/buzon/{mensaje_id}"): {"escuchado": True},
    ("POST", "/api/calidad/llamadas/{call_id}/evaluaciones"): {"puntajes": {}},
    ("POST", "/api/calidad/evaluaciones/{evaluacion_id}/revisar"): {},
}

# PUT que, contra un recurso PROPIO, tienen que funcionar. Es el control
# positivo: prueba que el cuerpo es válido y que la ruta sí escribe, así
# que el rechazo contra beta se debe al aislamiento y no a otra cosa.
_CONTROL_POSITIVO = [clave for clave in _CUERPOS if clave[0] == "PUT" and "flow" not in clave[1]]


def _recurso(ruta: str, parametro: str) -> str | None:
    if parametro == "route_id":
        return "inbound_route" if ruta.startswith("/api/inbound-routes") else "outbound_route"
    return _RECURSO_POR_PARAMETRO.get(parametro)


def _rutas_con_id():
    for ruta, metodos in rutas_api():
        if "{" not in ruta:
            continue
        for metodo in sorted(metodos - {"HEAD", "OPTIONS"}):
            yield metodo, ruta


def _url(ruta: str, empresa) -> str:
    def reemplazo(m):
        parametro = m.group(1)
        if parametro == "node_id":
            return "nodo1"
        return str(empresa.ids[_recurso(ruta, parametro)])

    return re.sub(r"\{(\w+)\}", reemplazo, ruta)


_ATAQUES = [(m, p) for m, p in _rutas_con_id() if p not in _FUERA_DE_ESTA_PRUEBA]


def test_todo_parametro_de_ruta_esta_declarado():
    """Una ruta nueva con un `{algo_id}` desconocido rompe acá, en vez de
    quedar sin prueba de aislamiento sin que nadie lo note."""
    desconocidos = sorted(
        {
            (p, prm)
            for _, p in _ATAQUES
            for prm in re.findall(r"\{(\w+)\}", p)
            if prm != "node_id" and _recurso(p, prm) is None
        }
    )
    assert not desconocidos, (
        "Rutas con parámetros sin recurso asociado. Agregalos a _RECURSO_POR_PARAMETRO "
        f"o, si no son de una empresa, a _FUERA_DE_ESTA_PRUEBA con el motivo: {desconocidos}"
    )


def _contiene_datos_de(texto: str, empresa) -> bool:
    return empresa.marca in texto or empresa.telefono in texto


@pytest.fixture(scope="module")
async def foto_beta_antes(mundo):
    return await foto_de_empresa(mundo.beta.id)


@pytest.mark.parametrize("metodo,ruta", _ATAQUES, ids=[f"{m} {p}" for m, p in _ATAQUES])
async def test_alfa_no_alcanza_recursos_de_beta(mundo, cliente, foto_beta_antes, metodo, ruta):
    kwargs = {}
    cuerpo = _CUERPOS.get((metodo, ruta))
    if cuerpo is not None:
        kwargs["json"] = cuerpo
    elif ruta.endswith("/audio") and metodo == "POST" or ruta.endswith("/greeting") and metodo == "POST":
        kwargs["files"] = {"file": ("a.wav", b"RIFF0000WAVEfmt ", "audio/wav")}

    resp = await cliente.request(metodo, _url(ruta, mundo.beta), headers=mundo.alfa.cabeceras(), **kwargs)

    # 404 (o 403), nada más. Un 2xx es una fuga; un 5xx, que llegó a
    # ejecutar algo; y un 422 significa que la prueba no probó nada: el
    # cuerpo de _CUERPOS no pasó la validación y nunca se buscó el recurso.
    assert resp.status_code in (403, 404), (
        f"{metodo} {ruta} con un id de beta respondió {resp.status_code}: {resp.text[:300]}"
    )
    assert not _contiene_datos_de(resp.text, mundo.beta), f"{metodo} {ruta} filtró datos de beta: {resp.text[:300]}"


async def test_beta_quedo_intacta_despues_de_todos_los_ataques(mundo, cliente, foto_beta_antes):
    # Corre después de los ataques por orden de definición en el módulo.
    despues = await foto_de_empresa(mundo.beta.id)
    cambiadas = [t for t in foto_beta_antes if foto_beta_antes[t] != despues[t]]
    assert not cambiadas, f"Los ataques de alfa modificaron datos de beta en: {cambiadas}"


@pytest.mark.parametrize("clave", _CONTROL_POSITIVO, ids=[f"{m} {p}" for m, p in _CONTROL_POSITIVO])
async def test_control_positivo_el_mismo_pedido_funciona_sobre_lo_propio(mundo, cliente, clave):
    metodo, ruta = clave
    resp = await cliente.request(metodo, _url(ruta, mundo.alfa), headers=mundo.alfa.cabeceras(), json=_CUERPOS[clave])
    assert resp.is_success, f"{metodo} {ruta} sobre un recurso propio respondió {resp.status_code}: {resp.text[:300]}"


def _listados():
    for ruta, metodos in rutas_api():
        if "{" not in ruta and "GET" in metodos:
            yield ruta


_LISTADOS = sorted(set(_listados()))


@pytest.mark.parametrize("ruta", _LISTADOS)
@pytest.mark.parametrize("rol", [permissions.ADMIN, permissions.SUPERVISOR, permissions.ASESOR])
async def test_ningun_listado_muestra_datos_de_otra_empresa(mundo, cliente, ruta, rol):
    resp = await cliente.get(ruta, headers=mundo.alfa.cabeceras(rol))
    # 502/503 son de lo que depende de FreeSWITCH, que en las pruebas no
    # existe; un 500 es un error sin manejar.
    assert resp.status_code != 500, f"GET {ruta} respondió 500"
    assert not _contiene_datos_de(resp.text, mundo.beta), f"GET {ruta} ({rol}) filtró datos de beta: {resp.text[:300]}"


@pytest.mark.parametrize(
    "ruta,esperado",
    [
        ("/api/extensions", "Recepcion alfa"),
        ("/api/trunks", "sip.alfa.carrier.test"),
        ("/api/voicebots", "bot-alfa"),
        ("/api/campaigns", "cobro-octubre"),
        ("/api/inbound-routes", "entrada-alfa"),
        ("/api/outbound-routes", "salida-alfa"),
        ("/api/calls", "5730011111"),
        ("/api/cobranza/debts", "Deudor alfa"),
        ("/api/users", "admin alfa"),
    ],
)
async def test_control_positivo_los_listados_muestran_lo_propio(mundo, cliente, ruta, esperado):
    """Sin esto, un listado que devolviera siempre vacío pasaría la prueba
    de arriba."""
    resp = await cliente.get(ruta, headers=mundo.alfa.cabeceras())
    assert resp.status_code == 200, f"GET {ruta}: {resp.status_code} {resp.text[:200]}"
    assert esperado in resp.text


async def test_grabacion_de_otra_empresa_no_se_entrega(mundo, cliente, tmp_path):
    """I3 con el archivo presente en disco: si el aislamiento fallara, se
    entregaría el audio. Sin el archivo, un 404 podría ser solo "no existe"."""
    from app.core.config import settings
    import os

    for e in (mundo.alfa, mundo.beta):
        with open(os.path.join(settings.recordings_dir, f"{e.marca}.wav"), "wb") as f:
            f.write(b"RIFF" + e.marca.encode())

    propia = await cliente.get(f"/api/calls/{mundo.alfa.ids['call']}/recording", headers=mundo.alfa.cabeceras())
    assert propia.status_code == 200 and b"alfa" in propia.content

    ajena = await cliente.get(f"/api/calls/{mundo.beta.ids['call']}/recording", headers=mundo.alfa.cabeceras())
    assert ajena.status_code == 404
    assert b"zzbeta" not in ajena.content
