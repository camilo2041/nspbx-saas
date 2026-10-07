"""Puente con el script del host que desbloquea IP (services/desbloqueos.py).

    docker compose exec -T backend python -m app.desbloqueos pendientes
    docker compose exec -T backend python -m app.desbloqueos resultado <id> <hecho|no_estaba|error> [detalle]

`pendientes` imprime una línea «id jail ip» por pedido, ya validados.
"""

import argparse
import asyncio
import sys

from app.core.database import async_session
from app.services import desbloqueos


async def _pendientes() -> int:
    async with async_session() as s:
        for p in await desbloqueos.pendientes(s):
            # Se revalida al imprimir: el script del host lo vuelve a hacer igual.
            if desbloqueos.JAIL_RE.fullmatch(p.jail):
                try:
                    print(p.id, p.jail, desbloqueos.ip_valida(p.ip))
                except desbloqueos.PedidoInvalido:
                    await desbloqueos.resolver(s, p.id, "error", "IP inválida")
    return 0


async def _resultado(pedido_id: int, estado: str, detalle: str | None) -> int:
    async with async_session() as s:
        try:
            await desbloqueos.resolver(s, pedido_id, estado, detalle)
        except desbloqueos.PedidoInvalido as exc:
            print(exc, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    a = argparse.ArgumentParser(description="Pedidos de desbloqueo de IP de fail2ban")
    sub = a.add_subparsers(dest="orden", required=True)
    sub.add_parser("pendientes")
    r = sub.add_parser("resultado")
    r.add_argument("id", type=int)
    r.add_argument("estado", choices=desbloqueos.ESTADOS_FINALES)
    r.add_argument("detalle", nargs="?")
    args = a.parse_args()
    if args.orden == "pendientes":
        sys.exit(asyncio.run(_pendientes()))
    sys.exit(asyncio.run(_resultado(args.id, args.estado, args.detalle)))
