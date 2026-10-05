"""Historial y restauración de versiones de un voizbot."""

from app.core import permissions


async def test_cada_guardado_es_una_version_y_se_puede_volver_atras(cliente, mundo):
    bot = mundo.alfa.ids["voicebot"]
    cab = mundo.alfa.cabeceras()
    flujo_bueno = {"nodes": [{"id": "inicio", "type": "start", "data": {}}], "edges": []}
    flujo_roto = {"nodes": [{"id": "roto", "type": "hangup", "data": {}}], "edges": []}

    r1 = await cliente.put(f"/api/voicebots/{bot}/flow", headers=cab, json=flujo_bueno)
    r2 = await cliente.put(f"/api/voicebots/{bot}/flow", headers=cab, json=flujo_roto)
    assert r2.json()["version"] == r1.json()["version"] + 1

    versiones = (await cliente.get(f"/api/voicebots/{bot}/versiones", headers=cab)).json()
    assert versiones[0]["version"] == r2.json()["version"] and versiones[0]["motivo"] == "flujo"
    assert versiones[0]["quien"] == "admin-alfa (admin)"
    buena = next(v for v in versiones if v["version"] == r1.json()["version"])

    resp = await cliente.post(f"/api/voicebots/{bot}/versiones/{buena['id']}/restaurar", headers=cab)
    assert resp.status_code == 200
    flujo = (await cliente.get(f"/api/voicebots/{bot}/flow", headers=cab)).json()
    assert [n["id"] for n in flujo["nodes"]] == ["inicio"]

    # La restauración también queda en el historial (se puede deshacer).
    ultima = (await cliente.get(f"/api/voicebots/{bot}/versiones", headers=cab)).json()[0]
    assert ultima["motivo"] == f"restaurada v{buena['version']}"


async def test_una_version_de_otro_bot_no_se_restaura(cliente, mundo):
    """La versión de beta sobre el bot de alfa: 404 (además del aislamiento
    por empresa, la versión tiene que ser de ESE bot)."""
    resp = await cliente.post(
        f"/api/voicebots/{mundo.alfa.ids['voicebot']}/versiones/{mundo.beta.ids['voicebot_version']}/restaurar",
        headers=mundo.alfa.cabeceras(),
    )
    assert resp.status_code == 404


async def test_quien_solo_puede_ver_no_restaura(cliente, mundo):
    from app.core.database import async_session
    from app.core.security import crear_token, hash_password
    from app.models import User

    async with async_session() as s:
        u = User(
            tenant_id=mundo.alfa.id, username="coord-versiones", full_name="Coord",
            password_hash=hash_password("clave-de-prueba"), role=permissions.COORDINADOR, enabled=True,
        )
        s.add(u)
        await s.commit()
        cab = {"Authorization": f"Bearer {crear_token(u.id, permissions.COORDINADOR, mundo.alfa.id)[0]}"}
    bot = mundo.alfa.ids["voicebot"]
    assert (await cliente.get(f"/api/voicebots/{bot}/versiones", headers=cab)).status_code == 200
    resp = await cliente.post(
        f"/api/voicebots/{bot}/versiones/{mundo.alfa.ids['voicebot_version']}/restaurar", headers=cab
    )
    assert resp.status_code == 403
