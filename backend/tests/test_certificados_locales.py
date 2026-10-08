"""Certificado real para instalaciones en red local (Fase K, punto 15).

Cloudflare y Let's Encrypt se reemplazan por dobles: el DNS anota lo que se
le pide y el «ACME» firma el CSR con una autoridad de prueba. El cliente
ACME de verdad se prueba contra Pebble (el servidor de pruebas de Let's
Encrypt) cuando está disponible: NSPBX_PEBBLE=https://localhost:14000/dir y
NSPBX_PEBBLE_CA=<ruta a pebble.minica.pem>.
"""

import os
from datetime import datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import delete

from app.api import instalaciones
from app.core.config import settings
from app.core.database import async_session
from app.core.limitador import LimiteIntentos
from app.models import AcmeCuenta, Instalacion
from app.services import acme, certificados_locales, licencia_firmada as lf, licencia_local

_PRIVADA, _PUBLICA = lf.generar_par()
_CA_CLAVE = ec.generate_private_key(ec.SECP256R1())
_CA_NOMBRE = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA de prueba")])


def _clave_y_csr(nombre: str, clave=None):
    clave = clave or ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre)]))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(nombre)]), critical=False)
        .sign(clave, hashes.SHA256())
    )
    return clave, csr.public_bytes(serialization.Encoding.PEM).decode()


def _firmar(csr_pem: str, dias: int = 90) -> str:
    csr = x509.load_pem_x509_csr(csr_pem.encode())
    ahora = datetime.utcnow()
    cert = (
        x509.CertificateBuilder().subject_name(csr.subject).issuer_name(_CA_NOMBRE).public_key(csr.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(ahora - timedelta(minutes=1))
        .not_valid_after(ahora + timedelta(days=dias)).sign(_CA_CLAVE, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class DnsFalso:
    def __init__(self, registro):
        self.r = registro

    async def fijar_a(self, nombre, ip):
        self.r.append(("A", nombre, ip))

    async def borrar_a(self, nombre):
        self.r.append(("-A", nombre))

    async def publicar_txt(self, nombre, valor):
        self.r.append(("TXT", nombre))
        return nombre

    async def quitar_txt(self, ref):
        self.r.append(("-TXT", ref))

    async def cerrar(self):
        pass


class AcmeFalso:
    dias = 90

    def __init__(self, *a, **k):
        self.kid = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        pass

    async def cuenta(self):
        return "https://acme.test/cuenta/1"

    async def certificado(self, csr_pem, publicar, quitar, esperar):
        ref = await publicar(f"_acme-challenge.{acme.nombres_del_csr(csr_pem)[0]}", "x")
        await esperar("x", "x")
        await quitar(ref)
        return _firmar(csr_pem, self.dias)


@pytest.fixture
def central(monkeypatch):
    registro = []
    monkeypatch.setattr(settings, "licencia_clave_privada", _PRIVADA)
    monkeypatch.setattr(settings, "dns_cloudflare_token", "tok")
    monkeypatch.setattr(settings, "dns_cloudflare_zona_id", "zona")
    monkeypatch.setattr(settings, "dominio_local_sufijo", "local.nspbx.test")
    monkeypatch.setattr(certificados_locales, "fabrica_dns", lambda: DnsFalso(registro))
    monkeypatch.setattr(certificados_locales.acme, "ClienteAcme", AcmeFalso)

    async def sin_espera(nombre, valor):
        return None

    monkeypatch.setattr(certificados_locales, "esperar_propagacion", sin_espera)
    for nombre in ("_POR_IP_ACTIVAR", "_POR_IP_LATIDO"):
        monkeypatch.setattr(instalaciones, nombre, LimiteIntentos(maximo=100, ventana=60, bloqueo=60))
    yield registro


async def _limpiar():
    async with async_session() as s:
        await s.execute(delete(Instalacion))
        await s.execute(delete(AcmeCuenta))
        await s.commit()


# --- Validaciones -----------------------------------------------------------------------


def test_solo_ip_de_red_local():
    assert certificados_locales.validar_ip(" 192.168.1.50 ") == "192.168.1.50"
    assert certificados_locales.validar_ip("10.0.0.7") == "10.0.0.7"
    assert certificados_locales.validar_ip("172.20.3.4") == "172.20.3.4"
    for mala in ("8.8.8.8", "172.32.0.1", "127.0.0.1", "169.254.1.1", "fe80::1", "pbx.local", ""):
        with pytest.raises(certificados_locales.ErrorCertificado):
            certificados_locales.validar_ip(mala)


def test_el_csr_pide_solo_su_subdominio():
    _, bueno = _clave_y_csr("clinica-7.local.nspbx.test")
    assert certificados_locales.validar_csr(bueno, "clinica-7.local.nspbx.test")
    _, otro = _clave_y_csr("banco.ejemplo.com")
    with pytest.raises(certificados_locales.ErrorCertificado, match="solo clinica-7"):
        certificados_locales.validar_csr(otro, "clinica-7.local.nspbx.test")
    _, corta = _clave_y_csr("clinica-7.local.nspbx.test", rsa.generate_private_key(65537, 1024))
    with pytest.raises(certificados_locales.ErrorCertificado, match="corta"):
        certificados_locales.validar_csr(corta, "clinica-7.local.nspbx.test")
    with pytest.raises(certificados_locales.ErrorCertificado):
        certificados_locales.validar_csr("no es un csr", "x")


# --- De punta a punta en la central -----------------------------------------------------


async def _activada(cliente, mundo):
    h = mundo.cabeceras_plataforma()
    inst = (await cliente.post("/api/plataforma/instalaciones", headers=h,
                               json={"empresa_id": mundo.alfa.id, "nombre": "Sede norte"})).json()
    act = (await cliente.post("/api/licencia/activar", json={"codigo": inst["codigo"]})).json()
    return inst, act, {"Authorization": f"Bearer {act['token']}"}


async def test_emite_renueva_y_retira(cliente, mundo, central):
    await _limpiar()
    try:
        inst, act, auth = await _activada(cliente, mundo)
        sub = act["subdominio"]
        assert sub == f"{mundo.alfa.slug}-{inst['id']}.local.nspbx.test"

        # IP pública o CSR de otro nombre: no.
        clave, csr = _clave_y_csr(sub)
        r = await cliente.post("/api/licencia/certificado", headers=auth, json={"ip_local": "8.8.8.8", "csr": csr})
        assert r.status_code == 422 and "red local" in r.json()["detail"]
        _, ajeno = _clave_y_csr("otro.local.nspbx.test")
        assert (await cliente.post("/api/licencia/certificado", headers=auth,
                                   json={"ip_local": "192.168.1.50", "csr": ajeno})).status_code == 422
        assert (await cliente.post("/api/licencia/certificado", json={"ip_local": "192.168.1.50", "csr": csr})).status_code == 401

        r = await cliente.post("/api/licencia/certificado", headers=auth, json={"ip_local": "192.168.1.50", "csr": csr})
        assert r.status_code == 200, r.text
        datos = r.json()
        cert = x509.load_pem_x509_certificate(datos["cadena"].encode())
        formato = (serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        assert cert.public_key().public_bytes(*formato) == clave.public_key().public_bytes(*formato)
        assert datos["dominio"] == sub
        assert ("A", sub, "192.168.1.50") in central
        assert ("TXT", f"_acme-challenge.{sub}") in central and ("-TXT", f"_acme-challenge.{sub}") in central

        fila = next(i for i in (await cliente.get("/api/plataforma/instalaciones", headers=mundo.cabeceras_plataforma())).json()["instalaciones"]
                    if i["id"] == inst["id"])
        assert fila["subdominio"] == sub and fila["ip_local"] == "192.168.1.50" and fila["cert_vence"]

        # Latido: con su certificado al día no se le manda nada; con uno viejo, sí.
        al_dia = cert.not_valid_after_utc.replace(tzinfo=None).isoformat()
        r = (await cliente.post("/api/licencia/latido", headers=auth, json={"cert_vence": al_dia})).json()
        assert "certificado" not in r
        viejo = (datetime.utcnow() + timedelta(days=5)).isoformat()
        r = (await cliente.post("/api/licencia/latido", headers=auth, json={"cert_vence": viejo})).json()
        assert r["certificado"]["cadena"] == datos["cadena"]

        # Cambió la IP del servidor: se corrige el A. Una pública se ignora.
        central.clear()
        await cliente.post("/api/licencia/latido", headers=auth, json={"ip_local": "192.168.1.77", "cert_vence": al_dia})
        assert central == [("A", sub, "192.168.1.77")]
        central.clear()
        await cliente.post("/api/licencia/latido", headers=auth, json={"ip_local": "200.1.1.1", "cert_vence": al_dia})
        assert central == []

        # Renovación: vence en menos de 30 días → certificado nuevo.
        async with async_session() as s:
            fila = await s.get(Instalacion, inst["id"])
            fila.cert_vence = datetime.utcnow() + timedelta(days=10)
            await s.commit()
        assert await certificados_locales.renovar_pendientes() == 1
        async with async_session() as s:
            fila = await s.get(Instalacion, inst["id"])
            assert fila.cert_vence > datetime.utcnow() + timedelta(days=80) and fila.ip_local == "192.168.1.77"

        # Revocada: su nombre deja de resolver.
        central.clear()
        await cliente.post(f"/api/plataforma/instalaciones/{inst['id']}/revocar", headers=mundo.cabeceras_plataforma())
        assert central == [("-A", sub)]
    finally:
        await _limpiar()


async def test_sin_dns_no_hay_subdominio(cliente, mundo, monkeypatch):
    monkeypatch.setattr(settings, "licencia_clave_privada", _PRIVADA)
    monkeypatch.setattr(instalaciones, "_POR_IP_ACTIVAR", LimiteIntentos(maximo=100, ventana=60, bloqueo=60))
    await _limpiar()
    try:
        _, act, auth = await _activada(cliente, mundo)
        assert act["subdominio"] is None
        _, csr = _clave_y_csr("x.local.nspbx.test")
        r = await cliente.post("/api/licencia/certificado", headers=auth, json={"ip_local": "192.168.1.5", "csr": csr})
        assert r.status_code == 422 and "DNS" in r.json()["detail"]
    finally:
        await _limpiar()


async def test_un_error_de_lets_encrypt_queda_anotado(cliente, mundo, central, monkeypatch):
    class AcmeQueFalla(AcmeFalso):
        async def certificado(self, *a, **k):
            raise acme.ErrorAcme("urn:ietf:params:acme:error:rateLimited: demasiados certificados")

    monkeypatch.setattr(certificados_locales.acme, "ClienteAcme", AcmeQueFalla)
    await _limpiar()
    try:
        inst, act, auth = await _activada(cliente, mundo)
        _, csr = _clave_y_csr(act["subdominio"])
        r = await cliente.post("/api/licencia/certificado", headers=auth, json={"ip_local": "10.1.2.3", "csr": csr})
        assert r.status_code == 502 and "rateLimited" in r.json()["detail"]
        async with async_session() as s:
            assert "rateLimited" in (await s.get(Instalacion, inst["id"])).cert_error
    finally:
        await _limpiar()


# --- En la instalación local ------------------------------------------------------------


def test_la_instalacion_solo_acepta_un_certificado_de_su_clave(tmp_path, monkeypatch):
    certs, traefik = tmp_path / "certs", tmp_path / "traefik"
    certs.mkdir(), traefik.mkdir()
    monkeypatch.setattr(settings, "certs_dir", str(certs))
    monkeypatch.setattr(settings, "traefik_dir", str(traefik))
    clave, csr = _clave_y_csr("clinica-7.local.nspbx.test")
    (certs / "panel.key").write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
    assert licencia_local.vence_certificado() is None

    _, ajeno = _clave_y_csr("clinica-7.local.nspbx.test")
    assert licencia_local.instalar_certificado(_firmar(ajeno)) is False
    assert not (certs / "panel.crt").exists()

    assert licencia_local.instalar_certificado(_firmar(csr, dias=90)) is True
    assert licencia_local.vence_certificado() > datetime.utcnow() + timedelta(days=89)
    yml = (traefik / "certificado.yml").read_text()
    assert "certFile: /certs/panel.crt" in yml and "keyFile: /certs/panel.key" in yml


# --- El cliente ACME contra Pebble (opcional) -------------------------------------------


@pytest.mark.skipif(not os.environ.get("NSPBX_PEBBLE"), reason="Pebble no está corriendo (ver el encabezado)")
async def test_cliente_acme_contra_pebble():
    _, csr = _clave_y_csr("clinica-9.local.nspbx.test")
    publicados = []

    async def publicar(nombre, valor):
        publicados.append((nombre, valor))
        return nombre

    async with acme.ClienteAcme(os.environ["NSPBX_PEBBLE"], acme.nueva_clave_cuenta(), "ops@nspbx.test",
                                verify=os.environ.get("NSPBX_PEBBLE_CA", True), espera_s=0.3) as c:
        cadena = await c.certificado(csr, publicar)
    assert cadena.count("BEGIN CERTIFICATE") >= 2
    assert publicados[0][0] == "_acme-challenge.clinica-9.local.nspbx.test" and len(publicados[0][1]) == 43
    assert acme.vence(cadena) > datetime.utcnow()


async def test_el_latido_informa_y_recibe_el_certificado_renovado(tmp_path, monkeypatch):
    import json as _json

    import httpx

    from app.models import LicenciaLocal

    certs, traefik = tmp_path / "certs", tmp_path / "traefik"
    certs.mkdir(), traefik.mkdir()
    monkeypatch.setattr(settings, "modo_instalacion", "local")
    monkeypatch.setattr(settings, "licencia_clave_publica", _PUBLICA)
    monkeypatch.setattr(settings, "central_url", "https://central.test")
    monkeypatch.setattr(settings, "ip_local", "192.168.1.50")
    monkeypatch.setattr(settings, "certs_dir", str(certs))
    monkeypatch.setattr(settings, "traefik_dir", str(traefik))
    clave, csr = _clave_y_csr("clinica-7.local.nspbx.test")
    (certs / "panel.key").write_bytes(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
    (certs / "panel.crt").write_text(_firmar(csr, dias=10))

    ahora = datetime.utcnow().replace(microsecond=0)
    doc = {"version": 1, "instalacion_id": 7, "empresa": {"nombre": "Clínica", "slug": "c", "business_type": "general", "modules": ["pbx"]},
           "licencia": {"plan": "pro", "status": "active", "expires_at": None, **{r: None for r in lf.RECURSOS}},
           "emitida": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "valida_hasta": (ahora + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    nueva = _firmar(csr, dias=90)
    pedidos = []

    def central(request):
        pedidos.append(_json.loads(request.content))
        return httpx.Response(200, json={**lf.firmar(doc, _PRIVADA), "certificado": {"dominio": "clinica-7.local.nspbx.test", "cadena": nueva}})

    from sqlalchemy import select

    from app.models import License, Tenant

    async with async_session() as s:
        t = await s.get(Tenant, 1)
        antes = (t.name, t.business_type, t.modules)
        lic = (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one_or_none()
        lic_antes = None if lic is None else {c: getattr(lic, c) for c in ("plan", "status", "expires_at", *lf.RECURSOS)}
        await licencia_local.aplicar(s, **lf.firmar(doc, _PRIVADA), token="tok")
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(central)) as c:
            assert await licencia_local.latir(c) is True
        assert pedidos[0]["ip_local"] == "192.168.1.50"
        assert datetime.fromisoformat(pedidos[0]["cert_vence"]) < datetime.utcnow() + timedelta(days=11)
        assert licencia_local.vence_certificado() > datetime.utcnow() + timedelta(days=89)
    finally:
        async with async_session() as s:
            await s.execute(delete(LicenciaLocal))
            t = await s.get(Tenant, 1)
            t.name, t.business_type, t.modules = antes
            lic = (await s.execute(select(License).where(License.tenant_id == 1))).scalar_one_or_none()
            if lic_antes is None and lic is not None:
                await s.delete(lic)
            elif lic_antes is not None:
                for c, v in lic_antes.items():
                    setattr(lic, c, v)
            await s.commit()
