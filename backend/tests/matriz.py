"""Qué permiso exige cada ruta, leído de sus dependencias (no de una lista
escrita a mano que se desactualiza). Lo usa test_matriz_permisos.py para
probar la matriz completa rol × ruta y para generar
docs/matriz-permisos.md."""

import inspect
from dataclasses import dataclass, field

from fastapi.routing import APIRoute

from app.core import permissions
from app.main import app

try:
    from fastapi.routing import iter_route_contexts
except ImportError:  # FastAPI anterior: app.routes trae las rutas con sus dependencias
    iter_route_contexts = None

ESCRITURA = {"POST", "PUT", "PATCH", "DELETE"}
ROLES_DE_EMPRESA = (permissions.ADMIN, permissions.SUPERVISOR, permissions.COORDINADOR, permissions.ASESOR)


@dataclass
class Guardia:
    siempre: set[str] = field(default_factory=set)  # requiere(...)
    escritura: set[str] = field(default_factory=set)  # escribir_requiere(...): solo al modificar
    modulos: set[str] = field(default_factory=set)
    global_: bool = False  # requiere_operador_global: nunca para una empresa con 2+ en la instalación

    def exige(self, metodo: str) -> set[str]:
        return self.siempre | (self.escritura if metodo in ESCRITURA else set())

    def vacia(self) -> bool:
        return not (self.siempre or self.escritura or self.global_)


def _recorrer(dependant, guardia: Guardia, vistos: set) -> None:
    for d in dependant.dependencies:
        c = d.call
        if id(c) in vistos:
            continue
        vistos.add(id(c))
        nombre = getattr(c, "__qualname__", "")
        try:
            libres = inspect.getclosurevars(c).nonlocals
        except (TypeError, ValueError):
            libres = {}
        if nombre.startswith("requiere."):
            guardia.siempre |= set(libres["permisos"])
        elif nombre.startswith("escribir_requiere."):
            guardia.escritura.add(libres["permiso"])
        elif nombre.startswith("requiere_modulo."):
            guardia.modulos.add(libres["modulo"])
        elif nombre == "requiere_operador_global":
            guardia.global_ = True
        _recorrer(d, guardia, vistos)


def rutas_con_guardia() -> list[tuple[str, str, Guardia]]:
    """(método, ruta, guardia) de cada ruta HTTP de /api/."""
    salida = []
    if iter_route_contexts is not None:
        for ctx in iter_route_contexts(app.routes):
            if not isinstance(ctx.original_route, APIRoute) or not ctx.path.startswith("/api/"):
                continue
            # Las dependencias del router (include_router(dependencies=…)) solo
            # están en el contexto efectivo, no en la ruta original.
            efectivo = getattr(ctx, "_route_context", None)
            dependant = efectivo.dependant if efectivo is not None else ctx.route.dependant
            for metodo in sorted((ctx.methods or set()) - {"HEAD", "OPTIONS"}):
                g = Guardia()
                _recorrer(dependant, g, set())
                salida.append((metodo, ctx.path, g))
    else:
        for r in app.routes:
            if isinstance(r, APIRoute) and r.path.startswith("/api/"):
                for metodo in sorted(r.methods - {"HEAD", "OPTIONS"}):
                    g = Guardia()
                    _recorrer(r.dependant, g, set())
                    salida.append((metodo, r.path, g))
    return sorted(salida, key=lambda x: (x[1], x[0]))
