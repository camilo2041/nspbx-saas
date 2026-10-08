"""La licencia de esta instalación local, desde la consola (lo usa `nspbx`).

    python -m app.cli.licencia estado     # resumen en JSON
    python -m app.cli.licencia renovar    # latido a la central ahora mismo
"""

import asyncio
import json
import sys

from app.core.database import async_session
from app.services import licencia_local


async def _estado() -> dict:
    async with async_session() as session:
        return await licencia_local.estado(session)


async def _renovar() -> dict:
    ok = await licencia_local.latir()
    return {"renovada": ok, **await _estado()}


def main() -> None:
    accion = sys.argv[1] if len(sys.argv) > 1 else "estado"
    if not licencia_local.es_local():
        print(json.dumps({"modo": "nube"}))
        return
    datos = asyncio.run(_renovar() if accion == "renovar" else _estado())
    print(json.dumps(datos, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
