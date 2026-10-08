"""Registros DNS de las instalaciones locales en Cloudflare (API v4).

Solo los que necesita services/certificados_locales.py: el A del
subdominio de cada instalación (a su IP de la red local) y el TXT temporal
del desafío dns-01. El token es de la CENTRAL y tiene que tener permiso
para editar solo la zona del dominio (Zone › DNS › Edit).
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

API = "https://api.cloudflare.com/client/v4"


class ErrorDns(Exception):
    pass


class Cloudflare:
    def __init__(self, token: str, zona_id: str, cliente: httpx.AsyncClient | None = None):
        self.zona = zona_id
        self._propio = cliente is None
        self._http = cliente or httpx.AsyncClient(timeout=20)
        self._cab = {"Authorization": f"Bearer {token}"}

    async def cerrar(self) -> None:
        if self._propio:
            await self._http.aclose()

    async def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        r = await self._http.request(metodo, f"{API}/zones/{self.zona}{ruta}", headers=self._cab, **kw)
        try:
            datos = r.json()
        except ValueError:
            raise ErrorDns(f"Cloudflare respondió {r.status_code}")
        if not datos.get("success"):
            errores = "; ".join(e.get("message", "") for e in datos.get("errors", [])) or str(r.status_code)
            raise ErrorDns(f"Cloudflare: {errores}")
        return datos

    async def _buscar(self, tipo: str, nombre: str) -> list[dict]:
        return (await self._pedir("GET", "/dns_records", params={"type": tipo, "name": nombre}))["result"]

    async def fijar_a(self, nombre: str, ip: str) -> None:
        """Crea o actualiza el A. Sin el proxy de Cloudflare (una IP privada
        no se puede proxear) y con TTL corto, por si cambia la IP."""
        cuerpo = {"type": "A", "name": nombre, "content": ip, "ttl": 300, "proxied": False}
        existentes = await self._buscar("A", nombre)
        if existentes:
            if existentes[0]["content"] != ip:
                await self._pedir("PUT", f"/dns_records/{existentes[0]['id']}", json=cuerpo)
        else:
            await self._pedir("POST", "/dns_records", json=cuerpo)

    async def borrar_a(self, nombre: str) -> None:
        for r in await self._buscar("A", nombre):
            await self._pedir("DELETE", f"/dns_records/{r['id']}")

    async def publicar_txt(self, nombre: str, valor: str) -> str:
        datos = await self._pedir("POST", "/dns_records", json={"type": "TXT", "name": nombre, "content": valor, "ttl": 60})
        return datos["result"]["id"]

    async def quitar_txt(self, registro_id: str) -> None:
        await self._pedir("DELETE", f"/dns_records/{registro_id}")


async def esperar_txt(nombre: str, valor: str, cliente: httpx.AsyncClient | None = None,
                      intentos: int = 40, espera_s: float = 3.0) -> None:
    """Vuelve cuando el TXT ya se ve desde internet (DNS sobre HTTPS de
    Cloudflare). Sin esto, Let's Encrypt puede consultar antes de que el
    registro exista y el pedido queda inválido."""
    propio = cliente is None
    cliente = cliente or httpx.AsyncClient(timeout=10)
    try:
        for _ in range(intentos):
            try:
                r = await cliente.get("https://cloudflare-dns.com/dns-query", params={"name": nombre, "type": "TXT"},
                                      headers={"Accept": "application/dns-json"})
                if any(valor in str(a.get("data", "")) for a in r.json().get("Answer", [])):
                    return
            except Exception as exc:
                logger.debug("Consulta del TXT: %s", exc)
            await asyncio.sleep(espera_s)
        raise ErrorDns(f"El TXT {nombre} no apareció a tiempo")
    finally:
        if propio:
            await cliente.aclose()
