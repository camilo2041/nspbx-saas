"""Alta, cambio y baja desde el panel: usuarios, extensiones, reglas de
salida, voizbots, campañas y empresas.

Cada prueba deja la base como la encontró: el mundo de las pruebas es
compartido y las de aislamiento comparan fotos de cada empresa."""

from app.core import permissions


async def test_usuario_con_extension_en_un_paso(cliente, mundo):
    h = mundo.alfa.cabeceras()
    r = await cliente.post("/api/users", headers=h, json={
        "username": "persona.nueva", "full_name": "Persona Nueva", "password": "clave-larga-1",
        "role": permissions.ASESOR, "crear_extension": True, "numero_extension": "1777",
    })
    assert r.status_code == 201, r.text
    u = r.json()
    try:
        exts = (await cliente.get("/api/extensions", headers=h)).json()
        ext = next(e for e in exts if e["number"] == "1777")
        assert u["extension_id"] == ext["id"] and ext["caller_id_name"] == "Persona Nueva"
        assert len(ext["password"]) >= 12 and "1777" not in ext["password"]

        # El mismo usuario otra vez, o la extensión ya asignada a otro: no.
        r = await cliente.post("/api/users", headers=h, json={
            "username": "persona.nueva", "full_name": "Otra", "password": "clave-larga-1", "role": permissions.SUPERVISOR,
        })
        assert r.status_code == 400
        r = await cliente.post("/api/users", headers=h, json={
            "username": "persona.dos", "full_name": "Otra", "password": "clave-larga-1",
            "role": permissions.ASESOR, "extension_id": ext["id"],
        })
        assert r.status_code == 400 and "ya está asignada" in r.json()["detail"]

        # Cambiar nombre y rol; la lista lo refleja.
        r = await cliente.put(f"/api/users/{u['id']}", headers=h, json={"full_name": "Persona Cambiada"})
        assert r.status_code == 200 and r.json()["full_name"] == "Persona Cambiada"
        assert any(x["full_name"] == "Persona Cambiada" for x in (await cliente.get("/api/users", headers=h)).json())

        assert (await cliente.post(f"/api/users/{u['id']}/cerrar-sesiones", headers=h)).status_code == 204
        assert (await cliente.post(f"/api/users/{u['id']}/mfa/reset", headers=h)).status_code == 200
    finally:
        assert (await cliente.delete(f"/api/users/{u['id']}", headers=h)).status_code == 204
        exts = (await cliente.get("/api/extensions", headers=h)).json()
        for e in exts:
            if e["number"] == "1777":
                assert (await cliente.delete(f"/api/extensions/{e['id']}", headers=h)).status_code == 204


async def test_un_asesor_necesita_extension(cliente, mundo):
    r = await cliente.post("/api/users", headers=mundo.alfa.cabeceras(), json={
        "username": "sin.extension", "full_name": "Sin Extensión", "password": "clave-larga-1", "role": permissions.ASESOR,
    })
    assert r.status_code == 400 and "extensión" in r.json()["detail"]


async def test_el_unico_admin_no_se_quita_ni_se_borra_a_si_mismo(cliente, mundo):
    h = mundo.alfa.cabeceras()
    admin = mundo.alfa.usuarios[permissions.ADMIN]
    r = await cliente.put(f"/api/users/{admin}", headers=h, json={"role": permissions.SUPERVISOR})
    assert r.status_code == 400 and "único administrador" in r.json()["detail"]
    r = await cliente.put(f"/api/users/{admin}", headers=h, json={"enabled": False})
    assert r.status_code == 400
    assert (await cliente.delete(f"/api/users/{admin}", headers=h)).status_code == 400
    assert (await cliente.post(f"/api/users/{admin}/mfa/reset", headers=h)).status_code == 400


async def test_roles_trae_los_permisos_efectivos(cliente, mundo):
    roles = (await cliente.get("/api/users/roles", headers=mundo.alfa.cabeceras())).json()
    valores = {r["value"] for r in roles}
    assert permissions.PLATAFORMA not in valores and permissions.ADMIN in valores
    asesor = next(r for r in roles if r["value"] == permissions.ASESOR)
    assert asesor["requiere_extension"] is True and asesor["permisos"]


async def test_extension_clave_y_numero(cliente, mundo):
    h = mundo.alfa.cabeceras()
    # Clave débil o con el número: no.
    for clave in ("12345678901234", "clave1888segura"):
        r = await cliente.post("/api/extensions", headers=h, json={"number": "1888", "password": clave})
        assert r.status_code == 422, clave
    # Número ya usado por la extensión sembrada.
    assert (await cliente.post("/api/extensions", headers=h, json={"number": "1000"})).status_code == 409

    r = await cliente.post("/api/extensions", headers=h, json={"number": "1888", "caller_id_name": "Bodega"})
    assert r.status_code == 201, r.text
    ext = r.json()
    try:
        assert (await cliente.get(f"/api/extensions/{ext['id']}", headers=h)).json()["number"] == "1888"
        # Mandar la misma clave = no tocarla; una nueva débil = no.
        r = await cliente.put(f"/api/extensions/{ext['id']}", headers=h, json={"password": ext["password"], "voicemail": False})
        assert r.status_code == 200 and r.json()["password"] == ext["password"] and r.json()["voicemail"] is False
        r = await cliente.put(f"/api/extensions/{ext['id']}", headers=h, json={"password": "corta"})
        assert r.status_code == 422
        # Pasarla a un número ocupado: no. Desactivarla: sí (FreeSWITCH no
        # responde en las pruebas y el cambio vale igual).
        assert (await cliente.put(f"/api/extensions/{ext['id']}", headers=h, json={"number": "1000"})).status_code == 409
        r = await cliente.put(f"/api/extensions/{ext['id']}", headers=h, json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
    finally:
        assert (await cliente.delete(f"/api/extensions/{ext['id']}", headers=h)).status_code == 204
    assert (await cliente.get(f"/api/extensions/{ext['id']}", headers=h)).status_code == 404


async def test_regla_de_salida_valida_troncal_y_patron(cliente, mundo):
    h = mundo.alfa.cabeceras()
    # La troncal de la otra empresa no existe para esta.
    r = await cliente.post("/api/outbound-routes", headers=h, json={
        "name": "ajena", "pattern": "60XXXXXXXX", "trunk_ids": str(mundo.beta.ids["trunk"]),
    })
    assert r.status_code == 422 and "No existe la troncal" in r.json()["detail"]

    r = await cliente.post("/api/outbound-routes", headers=h, json={
        "name": "fijos", "pattern": "60XXXXXXXX", "trunk_ids": str(mundo.alfa.ids["trunk"]), "priority": 20,
    })
    assert r.status_code == 201, r.text
    ruta = r.json()
    try:
        assert (await cliente.get(f"/api/outbound-routes/{ruta['id']}", headers=h)).json()["pattern"] == "60XXXXXXXX"
        # Quitar más dígitos de los que tiene el patrón: no.
        r = await cliente.put(f"/api/outbound-routes/{ruta['id']}", headers=h, json={"pattern": "6X", "strip_digits": 3})
        assert r.status_code == 422
        r = await cliente.put(f"/api/outbound-routes/{ruta['id']}", headers=h,
                              json={"trunk_ids": str(mundo.beta.ids["trunk"])})
        assert r.status_code == 422
        r = await cliente.put(f"/api/outbound-routes/{ruta['id']}", headers=h, json={"strip_digits": 2, "prepend": "57"})
        assert r.status_code == 200 and r.json()["strip_digits"] == 2
        orden = [x["id"] for x in (await cliente.get("/api/outbound-routes", headers=h)).json()]
        assert orden.index(mundo.alfa.ids["outbound_route"]) < orden.index(ruta["id"])  # prioridad 10 antes que 20
    finally:
        assert (await cliente.delete(f"/api/outbound-routes/{ruta['id']}", headers=h)).status_code == 204
    assert (await cliente.get(f"/api/outbound-routes/{ruta['id']}", headers=h)).status_code == 404


async def test_voizbot_guarda_version_al_cambiar(cliente, mundo):
    h = mundo.alfa.cabeceras()
    assert (await cliente.post("/api/voicebots", headers=h, json={"name": "raro", "bot_type": "otro"})).status_code == 400
    r = await cliente.post("/api/voicebots", headers=h, json={"name": "recepcion-prueba", "welcome_message": "Hola"})
    assert r.status_code == 201, r.text
    bot = r.json()
    try:
        r = await cliente.put(f"/api/voicebots/{bot['id']}", headers=h, json={"welcome_message": "Buenos días"})
        assert r.status_code == 200 and r.json()["welcome_message"] == "Buenos días"
        versiones = (await cliente.get(f"/api/voicebots/{bot['id']}/versiones", headers=h)).json()
        assert versiones and versiones[0]["motivo"] == "ajustes"
        flujo = {"nodes": [{"id": "n1", "type": "hangup", "position": {"x": 0, "y": 0}, "data": {"label": "Colgar"}}], "edges": []}
        assert (await cliente.put(f"/api/voicebots/{bot['id']}/flow", headers=h, json=flujo)).status_code == 200
        assert (await cliente.get(f"/api/voicebots/{bot['id']}/flow", headers=h)).json()["nodes"][0]["id"] == "n1"
    finally:
        assert (await cliente.delete(f"/api/voicebots/{bot['id']}", headers=h)).status_code == 204
    assert (await cliente.get(f"/api/voicebots/{bot['id']}", headers=h)).status_code == 404


async def test_campana_numeros_y_secreto_del_crm(cliente, mundo):
    h = mundo.alfa.cabeceras()
    # Una troncal o un voizbot de la otra empresa no se pueden referir.
    r = await cliente.post("/api/campaigns", headers=h, json={"name": "ajena", "trunk_id": mundo.beta.ids["trunk"]})
    assert r.status_code in (400, 404, 422)

    r = await cliente.post("/api/campaigns", headers=h, json={
        "name": "prueba-crud", "trunk_id": mundo.alfa.ids["trunk"], "voicebot_id": mundo.alfa.ids["voicebot"],
        "crm_url": "https://crm.alfa.test/ficha?tel={telefono}",
    })
    assert r.status_code == 201, r.text
    camp = r.json()
    try:
        assert (await cliente.post("/api/campaigns", headers=h, json={"name": "prueba-crud"})).status_code == 400
        s1 = (await cliente.post(f"/api/campaigns/{camp['id']}/crm-secreto", headers=h)).json()["secreto"]
        assert s1 == (await cliente.post(f"/api/campaigns/{camp['id']}/crm-secreto", headers=h)).json()["secreto"]
        assert s1 != (await cliente.post(f"/api/campaigns/{camp['id']}/crm-secreto?rotar=true", headers=h)).json()["secreto"]

        r = await cliente.post(f"/api/campaigns/{camp['id']}/numbers", headers=h, json={"numbers": [
            {"phone": "3109990001", "vars": {"nombre": "Ana"}}, {"phone": "3109990002"},
        ]})
        assert r.status_code == 201 and r.json()["added"] == 2, r.text
        nums = (await cliente.get(f"/api/campaigns/{camp['id']}/numbers", headers=h)).json()
        filas = nums["items"] if isinstance(nums, dict) else nums
        assert {n["phone"] for n in filas} == {"3109990001", "3109990002"}
        stats = (await cliente.get(f"/api/campaigns/{camp['id']}/stats", headers=h)).json()
        assert stats["total"] == 2 and stats["pending"] == 2

        r = await cliente.put(f"/api/campaigns/{camp['id']}", headers=h, json={"max_concurrency": 3})
        assert r.status_code == 200 and r.json()["max_concurrency"] == 3
        assert (await cliente.delete(f"/api/campaigns/{camp['id']}/numbers/{filas[0]['id']}", headers=h)).status_code == 204
        assert (await cliente.get(f"/api/campaigns/{camp['id']}/stats", headers=h)).json()["total"] == 1
    finally:
        assert (await cliente.delete(f"/api/campaigns/{camp['id']}", headers=h)).status_code == 204
    assert (await cliente.get(f"/api/campaigns/{camp['id']}", headers=h)).status_code == 404


async def test_empresa_de_punta_a_punta_desde_la_plataforma(cliente, mundo):
    h = mundo.cabeceras_plataforma()
    # Un administrador de empresa no administra empresas.
    assert (await cliente.get("/api/tenants", headers=mundo.alfa.cabeceras())).status_code == 403

    r = await cliente.post("/api/tenants", headers=h, json={
        "name": "Empresa Gamma", "slug": "gamma-prueba", "sip_domain": "gamma-prueba.pbx.test", "modules": ["pbx"],
    })
    assert r.status_code == 201, r.text
    t = r.json()
    try:
        assert t["admin_username"] == "admin.gamma-prueba" and len(t["admin_password"]) >= 12
        assert t["subdomain"] == "gamma-prueba" and t["users_count"] == 1
        # Slug repetido: no.
        r = await cliente.post("/api/tenants", headers=h, json={
            "name": "Otra", "slug": "gamma-prueba", "sip_domain": "otra.pbx.test",
        })
        assert r.status_code == 400
        # Dominio SIP de otra empresa: no.
        r = await cliente.put(f"/api/tenants/{t['id']}", headers=h, json={"sip_domain": mundo.alfa.dominio})
        assert r.status_code == 400
        r = await cliente.put(f"/api/tenants/{t['id']}", headers=h, json={"outbound_blocked": True, "modules": ["pbx", "voicebot"]})
        assert r.status_code == 200 and r.json()["outbound_blocked"] is True and set(r.json()["modules"]) == {"pbx", "voicebot"}

        r = await cliente.put(f"/api/tenants/{t['id']}/licencia", headers=h, json={"max_extensions": 2})
        assert r.status_code == 200 and r.json()["max_extensions"] == 2
        assert (await cliente.get(f"/api/tenants/{t['id']}/licencia", headers=h)).json()["max_extensions"] == 2
        assert (await cliente.post(f"/api/tenants/{t['id']}/cerrar-sesiones", headers=h)).json() == {"usuarios": 1}
        # FreeSWITCH no responde en las pruebas: se dice, no se finge.
        assert (await cliente.post(f"/api/tenants/{t['id']}/salientes/colgar", headers=h)).status_code == 502
    finally:
        assert (await cliente.delete(f"/api/tenants/{t['id']}", headers=h)).status_code == 204
    assert not any(x["id"] == t["id"] for x in (await cliente.get("/api/tenants", headers=h)).json())
    assert (await cliente.put("/api/tenants/999999", headers=h, json={"name": "Nadie"})).status_code == 404
