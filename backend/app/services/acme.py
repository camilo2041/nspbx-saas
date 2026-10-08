"""Cliente ACME (RFC 8555) mínimo, para certificados por DNS-01.

Lo usa la central para sacar el certificado de Let's Encrypt de cada
instalación local (services/certificados_locales.py). Solo hace lo que
necesitamos: una cuenta con clave EC P-256, un pedido de un nombre, el
desafío dns-01, finalizar con el CSR que manda la instalación (su clave
privada nunca sale de su servidor) y bajar la cadena.

Se escribe aparte en vez de usar la librería de certbot porque esta es
asíncrona, usa httpx y cryptography (ya están en el proyecto) y cabe en un
archivo. Se prueba contra Pebble, el servidor ACME de pruebas de Let's
Encrypt (tests/test_acme.py).
"""

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

logger = logging.getLogger(__name__)

LETSENCRYPT = "https://acme-v02.api.letsencrypt.org/directory"
LETSENCRYPT_PRUEBAS = "https://acme-staging-v02.api.letsencrypt.org/directory"


class ErrorAcme(Exception):
    """El servidor ACME rechazó algo (con su motivo) o no respondió a tiempo."""


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def nueva_clave_cuenta() -> str:
    """Clave EC P-256 de la cuenta ACME, en PEM."""
    clave = ec.generate_private_key(ec.SECP256R1())
    return clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()


def _jwk(clave: ec.EllipticCurvePrivateKey) -> dict:
    num = clave.public_key().public_numbers()
    return {"crv": "P-256", "kty": "EC", "x": _b64(num.x.to_bytes(32, "big")), "y": _b64(num.y.to_bytes(32, "big"))}


def huella_jwk(jwk: dict) -> str:
    canon = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")}, separators=(",", ":"), sort_keys=True)
    return _b64(hashlib.sha256(canon.encode()).digest())


def valor_txt(token: str, huella: str) -> str:
    """Lo que va en el registro TXT _acme-challenge del nombre."""
    return _b64(hashlib.sha256(f"{token}.{huella}".encode()).digest())


def nombres_del_csr(csr_pem: str) -> list[str]:
    csr = x509.load_pem_x509_csr(csr_pem.encode())
    try:
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        nombres = san.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        nombres = []
    cn = [a.value for a in csr.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)]
    return sorted({n.lower() for n in [*nombres, *cn]})


class ClienteAcme:
    def __init__(self, directorio: str, clave_pem: str, correo: str = "", verify: bool | str = True,
                 espera_s: float = 2.0, intentos: int = 60):
        self.url_directorio = directorio
        self.clave = serialization.load_pem_private_key(clave_pem.encode(), password=None)
        self.jwk = _jwk(self.clave)
        self.huella = huella_jwk(self.jwk)
        self.correo = correo
        self.verify = verify
        self.espera_s = espera_s
        self.intentos = intentos
        self.kid: str | None = None
        self._dir: dict | None = None
        self._nonce: str | None = None
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=30, verify=self.verify)
        r = await self._http.get(self.url_directorio)
        r.raise_for_status()
        self._dir = r.json()
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    # --- JWS --------------------------------------------------------------------------

    async def _nuevo_nonce(self) -> str:
        r = await self._http.head(self._dir["newNonce"])
        return r.headers["Replay-Nonce"]

    def _firmar(self, url: str, payload: dict | None, nonce: str) -> dict:
        protegido = {"alg": "ES256", "nonce": nonce, "url": url}
        if self.kid:
            protegido["kid"] = self.kid
        else:
            protegido["jwk"] = self.jwk
        p64 = _b64(json.dumps(protegido).encode())
        c64 = "" if payload is None else _b64(json.dumps(payload).encode())
        der = self.clave.sign(f"{p64}.{c64}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return {"protected": p64, "payload": c64, "signature": _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}

    async def _post(self, url: str, payload: dict | None, aceptar: str = "application/json") -> httpx.Response:
        """POST firmado. payload None = «POST-as-GET». Reintenta un badNonce."""
        for intento in range(3):
            nonce = self._nonce or await self._nuevo_nonce()
            self._nonce = None
            r = await self._http.post(url, json=self._firmar(url, payload, nonce),
                                      headers={"Content-Type": "application/jose+json", "Accept": aceptar})
            self._nonce = r.headers.get("Replay-Nonce")
            if r.status_code < 400:
                return r
            try:
                problema = r.json()
            except ValueError:
                problema = {"detail": r.text[:200]}
            if problema.get("type", "").endswith(":badNonce") and intento < 2:
                continue
            raise ErrorAcme(f"{problema.get('type', r.status_code)}: {problema.get('detail', '')}")
        raise ErrorAcme("El servidor ACME rechazó el nonce varias veces")

    async def _esperar(self, url: str, listos: set[str], fallidos: set[str]) -> dict:
        for _ in range(self.intentos):
            datos = (await self._post(url, None)).json()
            if datos.get("status") in listos:
                return datos
            if datos.get("status") in fallidos:
                error = datos.get("error") or next((c.get("error") for c in datos.get("challenges", []) if c.get("error")), {})
                raise ErrorAcme(f"Quedó «{datos.get('status')}»: {error.get('detail', error) if error else 'sin detalle'}")
            await asyncio.sleep(self.espera_s)
        raise ErrorAcme(f"{url} no terminó a tiempo")

    # --- Flujo --------------------------------------------------------------------------

    async def cuenta(self) -> str:
        payload: dict = {"termsOfServiceAgreed": True}
        if self.correo:
            payload["contact"] = [f"mailto:{self.correo}"]
        r = await self._post(self._dir["newAccount"], payload)
        self.kid = r.headers["Location"]
        return self.kid

    async def certificado(
        self,
        csr_pem: str,
        publicar_txt: Callable[[str, str], Awaitable[object]],
        quitar_txt: Callable[[object], Awaitable[None]] | None = None,
        esperar_propagacion: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> str:
        """La cadena PEM para el nombre del CSR.

        `publicar_txt(nombre, valor)` crea el TXT y devuelve con qué borrarlo
        (`quitar_txt`); `esperar_propagacion(nombre, valor)` vuelve cuando el
        TXT ya se ve en internet."""
        if not self.kid:
            await self.cuenta()
        nombres = nombres_del_csr(csr_pem)
        if len(nombres) != 1:
            raise ErrorAcme("El CSR tiene que pedir exactamente un nombre")
        r = await self._post(self._dir["newOrder"], {"identifiers": [{"type": "dns", "value": nombres[0]}]})
        url_pedido, pedido = r.headers["Location"], r.json()
        publicados = []
        try:
            for url_authz in pedido["authorizations"]:
                authz = (await self._post(url_authz, None)).json()
                if authz["status"] == "valid":
                    continue
                desafio = next((c for c in authz["challenges"] if c["type"] == "dns-01"), None)
                if not desafio:
                    raise ErrorAcme("El servidor ACME no ofrece el desafío dns-01")
                nombre_txt = f"_acme-challenge.{authz['identifier']['value']}"
                valor = valor_txt(desafio["token"], self.huella)
                publicados.append(await publicar_txt(nombre_txt, valor))
                if esperar_propagacion:
                    await esperar_propagacion(nombre_txt, valor)
                await self._post(desafio["url"], {})
                await self._esperar(url_authz, {"valid"}, {"invalid", "revoked", "expired", "deactivated"})
            csr_der = x509.load_pem_x509_csr(csr_pem.encode()).public_bytes(serialization.Encoding.DER)
            await self._post(pedido["finalize"], {"csr": _b64(csr_der)})
            pedido = await self._esperar(url_pedido, {"valid"}, {"invalid"})
            r = await self._post(pedido["certificate"], None, aceptar="application/pem-certificate-chain")
            return r.text
        finally:
            if quitar_txt:
                for ref in publicados:
                    try:
                        await quitar_txt(ref)
                    except Exception as exc:  # un TXT que queda no rompe nada
                        logger.warning("No se pudo borrar el TXT del desafío: %s", exc)


def vence(cadena_pem: str):
    """Fecha de vencimiento (UTC, naive) del primer certificado de la cadena."""
    cert = x509.load_pem_x509_certificate(cadena_pem.encode())
    return cert.not_valid_after_utc.replace(tzinfo=None)
