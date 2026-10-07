"""Prueba de humo desde la consola del servidor (services/humo.py).

    docker compose exec backend python -m app.humo --empresa <slug> [--buzon 101] [--grupo 8000]

Sale con código 1 si algún paso falló (para usarlo después de cada despliegue).
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.database import async_session
from app.models import Tenant
from app.services import humo

MARCAS = {"ok": "✔", "fallo": "✘", "aviso": "!", "omitido": "-"}


async def _main(slug: str, buzon: str | None, grupo: str | None) -> int:
    async with async_session() as s:
        empresa = (await s.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if empresa is None:
        print(f"No hay una empresa con el slug {slug!r}", file=sys.stderr)
        return 2
    r = await humo.probar(empresa.id, buzon, grupo)
    print(f"Prueba de humo de {r['empresa']} ({r['segundos']} s)")
    for p in r["pasos"]:
        print(f"  {MARCAS.get(p['estado'], '?')} {p['titulo']}: {p['detalle']}")
    print("Resultado:", "todo bien" if r["ok"] else "hay fallos")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    a = argparse.ArgumentParser(description="Prueba de humo contra la central real")
    a.add_argument("--empresa", required=True, help="slug de la empresa")
    a.add_argument("--buzon", help="extensión con buzón para dejar un mensaje de prueba")
    a.add_argument("--grupo", help="número del grupo para entrar a la fila (sus agentes pueden oír timbrar)")
    args = a.parse_args()
    sys.exit(asyncio.run(_main(args.empresa, args.buzon, args.grupo)))
