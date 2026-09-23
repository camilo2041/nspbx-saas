"""Permisos por rol, configurables por empresa.

La matriz de `core/permissions.py` es el valor de fábrica; acá se guardan
las diferencias y se recarga el caché del proceso, que es lo que consulta
`requiere()` en cada petición.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import usuario_actual
from app.core.database import get_admin_session, get_session
from app.models import RolePermission, User

router = APIRouter(prefix="/api/role-permissions", tags=["role-permissions"])


class MatrizRol(BaseModel):
    role: str
    permisos: dict[str, bool] = Field(default_factory=dict)


async def recargar_cache(session: AsyncSession) -> None:
    """Relee TODA la tabla al caché del proceso.

    Se relee entera y no solo la empresa que cambió porque el caché es
    global al proceso: mantener una parte actualizada y otra no es la
    clase de estado a medias que después nadie entiende.
    """
    filas = (await session.execute(select(RolePermission))).scalars().all()
    permissions.cargar_overrides(filas)


@router.get("")
async def leer(usuario: User = Depends(usuario_actual)):
    """Todo lo que la pantalla necesita: qué roles hay, qué permisos
    existen, cuáles tiene cada rol hoy y qué casillas están fijas."""
    roles = [r for r in permissions.ROLES if permissions.personalizable(r)]
    return {
        "roles": [
            {
                "value": r,
                "label": permissions.ETIQUETAS[r],
                "description": permissions.DESCRIPCIONES[r],
            }
            for r in roles
        ],
        "permisos": [
            {"value": p, "label": permissions.ETIQUETAS_PERMISOS[p]}
            for p in permissions.TODOS_LOS_PERMISOS
            # Los que ninguna empresa puede otorgar no se muestran: una
            # casilla que siempre está apagada y nunca se deja encender
            # solo genera la duda de por qué no funciona.
            if permissions.editable(permissions.ASESOR, p)
        ],
        "matriz": {
            r: {
                p: p in permissions.permisos_de(r, usuario.tenant_id)
                for p in permissions.TODOS_LOS_PERMISOS
                if permissions.editable(permissions.ASESOR, p)
            }
            for r in roles
        },
        # Casillas que la interfaz debe mostrar marcadas y deshabilitadas.
        "fijos": {
            r: [
                p
                for p in permissions.TODOS_LOS_PERMISOS
                if permissions.editable(permissions.ASESOR, p) and not permissions.editable(r, p)
            ]
            for r in roles
        },
        "por_defecto": {
            r: sorted(permissions.PERMISOS_POR_ROL.get(r, frozenset()))
            for r in roles
        },
    }


@router.put("")
async def guardar(
    payload: MatrizRol,
    usuario: User = Depends(usuario_actual),
    session: AsyncSession = Depends(get_session),
    admin_session: AsyncSession = Depends(get_admin_session),
):
    """Reemplaza los permisos de UN rol en esta empresa."""
    if not permissions.personalizable(payload.role):
        raise HTTPException(status_code=422, detail="Ese rol no se puede personalizar")
    if usuario.tenant_id is None:
        raise HTTPException(status_code=422, detail="El usuario de plataforma no tiene empresa que configurar")

    desconocidos = set(payload.permisos) - set(permissions.TODOS_LOS_PERMISOS)
    if desconocidos:
        raise HTTPException(status_code=422, detail=f"Permiso desconocido: {', '.join(sorted(desconocidos))}")

    base = permissions.PERMISOS_POR_ROL.get(payload.role, frozenset())

    # Se borran las diferencias anteriores y se reescriben: guardar solo
    # lo que difiere del valor de fábrica mantiene la tabla chica y hace
    # que un permiso nuevo del producto lo hereden todos los roles.
    previas = (
        await session.execute(select(RolePermission).where(RolePermission.role == payload.role))
    ).scalars().all()
    for fila in previas:
        await session.delete(fila)

    for permiso, permitido in payload.permisos.items():
        if not permissions.editable(payload.role, permiso):
            # Silencioso a propósito: la interfaz ya las muestra
            # deshabilitadas, y fallar acá obligaría a que conozca las
            # reglas del servidor para armar un PUT válido.
            continue
        if permitido == (permiso in base):
            continue
        session.add(
            RolePermission(
                tenant_id=usuario.tenant_id,
                role=payload.role,
                permission=permiso,
                allowed=permitido,
            )
        )

    await session.commit()
    # Con la sesión del dueño: el caché es de TODO el proceso y tiene que
    # incluir las demás empresas, que el aislamiento de la sesión normal
    # oculta. Si se recargara con la sesión de esta empresa, las otras
    # perderían sus personalizaciones hasta el próximo reinicio.
    await recargar_cache(admin_session)
    return {"ok": True, "permisos": sorted(permissions.permisos_de(payload.role, usuario.tenant_id))}
