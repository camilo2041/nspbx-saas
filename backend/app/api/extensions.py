from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, tenant_de_sesion
from app.models import Extension, Tenant, Trunk
from app.schemas import CallRequest, ExtensionCreate, ExtensionOut, ExtensionUpdate
from app.services import licensing
from app.services.config_generator import orden_troncales
from app.services.esl import originate_bridge, reloadxml

router = APIRouter(prefix="/api/extensions", tags=["extensions"])


@router.get("", response_model=list[ExtensionOut])
async def list_extensions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Extension).order_by(Extension.number))
    return result.scalars().all()


@router.post("", response_model=ExtensionOut, status_code=status.HTTP_201_CREATED)
async def create_extension(payload: ExtensionCreate, session: AsyncSession = Depends(get_session)):
    # Límite de la licencia: no se pueden superar las extensiones del plan.
    tid = tenant_de_sesion(session)
    if tid is not None:
        lic = await licensing.obtener(session, tid)
        if not await licensing.hay_cupo(session, lic, "max_extensions", await licensing.contar_extensiones(session, tid)):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Alcanzaste el límite de extensiones de tu plan. Mejora la licencia para agregar más.",
            )
    ext = Extension(**payload.model_dump())
    session.add(ext)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Número de extensión duplicado")
    await session.refresh(ext)
    return ext


@router.get("/{extension_id}", response_model=ExtensionOut)
async def get_extension(extension_id: int, session: AsyncSession = Depends(get_session)):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    return ext


@router.put("/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: int, payload: ExtensionUpdate, session: AsyncSession = Depends(get_session)
):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ext, field, value)
    await session.commit()
    await session.refresh(ext)
    return ext


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(extension_id: int, session: AsyncSession = Depends(get_session)):
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    await session.delete(ext)
    await session.commit()


@router.post("/{extension_id}/call")
async def call_extension(
    extension_id: int, payload: CallRequest, session: AsyncSession = Depends(get_session)
):
    """Click-to-call: hace sonar la extensión y, al contestar, la bridgea al destino
    (otra extensión interna, o un número externo vía la troncal indicada)."""
    ext = await session.get(Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    if not ext.enabled:
        raise HTTPException(status_code=400, detail="La extensión está deshabilitada")

    destination = payload.destination.strip()

    if payload.trunk_id is not None:
        trunk = await session.get(Trunk, payload.trunk_id)
        if not trunk:
            raise HTTPException(status_code=404, detail="Troncal no encontrada")
        if not trunk.enabled:
            raise HTTPException(status_code=400, detail="La troncal está deshabilitada")
        # La troncal elegida va primero; si hay otras habilitadas de la
        # misma empresa, quedan de respaldo — si esta no contesta o la
        # rechaza, FreeSWITCH prueba la siguiente sola, sin que el clic a
        # llamar se pierda por una troncal caída.
        todas_troncales = (
            await session.execute(select(Trunk).where(Trunk.tenant_id == ext.tenant_id))
        ).scalars().all()
        cadena = orden_troncales(todas_troncales, principal_id=trunk.id)
        # El gateway en sofia lleva el slug de la empresa como prefijo.
        tenant_trunk = await session.get(Tenant, trunk.tenant_id)
        slug = tenant_trunk.slug if tenant_trunk else "x"
        bridge_target = "|".join(f"sofia/gateway/{slug}_{t.name}/{destination}" for t in cadena)
    else:
        target_ext = await session.execute(
            select(Extension).where(Extension.number == destination, Extension.enabled.is_(True))
        )
        if not target_ext.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Destino no es una extensión interna válida; especifica una troncal para llamar a un número externo",
            )
        bridge_target = f"user/{destination}"

    try:
        # El dominio de la EMPRESA de la extensión (el de su directorio en
        # FreeSWITCH), no una variable de proceso: con varias empresas cada
        # extensión vive en la suya.
        tenant = await session.get(Tenant, ext.tenant_id)
        dominio = tenant.sip_domain if tenant else "nspbx.local"
        out = await originate_bridge(
            from_endpoint=f"user/{ext.number}@{dominio}",
            bridge_target=bridge_target,
            caller_id=ext.caller_id_name or ext.number,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}


@router.post("/reload")
async def extensions_reload():
    try:
        out = await reloadxml()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FreeSWITCH no disponible: {exc}")
    return {"ok": True, "output": out}
