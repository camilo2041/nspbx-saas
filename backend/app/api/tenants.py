"""Empresas (tenants) — lo administra SOLO el rol de plataforma.

Un tenant es un dominio SIP más un contexto de dialplan (ver
docs/arquitectura-multitenant.md). Todo este router usa la sesión del
DUEÑO (sin Row-Level Security) porque el operador de la plataforma
administra TODAS las empresas, no una en particular — el aislamiento
entre empresas lo aplica cada empresa sobre sus propios datos, no acá.

Al crear una empresa se siembran sus Ajustes (fs_domain sale del dominio
SIP) y se crea su primer administrador; la contraseña se devuelve UNA
sola vez. Después, quien entra con ese usuario queda encerrado en su
empresa por RLS.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere
from app.core.database import get_admin_session
from app.core.security import hash_password
from app.models import Extension, License, Tenant, User
from app.schemas import LicenseOut, LicenseUpdate, TenantCreate, TenantCreatedOut, TenantOut, TenantUpdate
from app.services import licensing
from app.services.ajustes import get_or_create_settings

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


async def _out(session: AsyncSession, t: Tenant) -> TenantOut:
    users = (
        await session.execute(select(func.count(User.id)).where(User.tenant_id == t.id))
    ).scalar() or 0
    extensions = (
        await session.execute(select(func.count(Extension.id)).where(Extension.tenant_id == t.id))
    ).scalar() or 0
    lic = await licensing.obtener(session, t.id)
    return TenantOut(
        id=t.id,
        name=t.name,
        slug=t.slug,
        sip_domain=t.sip_domain,
        subdomain=t.subdomain,
        business_type=t.business_type,
        modules=t.modules_list,
        enabled=t.enabled,
        created_at=t.created_at,
        users_count=users,
        extensions_count=extensions,
        licencia=await _lic_out(session, lic),
    )


async def _lic_out(session: AsyncSession, lic: License) -> LicenseOut:
    return LicenseOut(
        plan=lic.plan,
        status=lic.status,
        estado=licensing.estado(lic),
        started_at=lic.started_at,
        expires_at=lic.expires_at,
        max_extensions=licensing.limite(lic, "max_extensions"),
        max_trunks=licensing.limite(lic, "max_trunks"),
        max_concurrent_calls=licensing.limite(lic, "max_concurrent_calls"),
        max_campaigns=licensing.limite(lic, "max_campaigns"),
    )


@router.get("", response_model=list[TenantOut])
async def list_tenants(session: AsyncSession = Depends(get_admin_session)):
    rows = (await session.execute(select(Tenant).order_by(Tenant.id))).scalars().all()
    return [await _out(session, t) for t in rows]


@router.post("", response_model=TenantCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(payload: TenantCreate, session: AsyncSession = Depends(get_admin_session)):
    ten = Tenant(
        name=payload.name.strip(),
        slug=payload.slug.strip().lower(),
        sip_domain=payload.sip_domain.strip(),
        # El subdominio del panel: si no se indica, se usa el slug (es el
        # valor más razonable y evita dejar una empresa sin subdominio).
        subdomain=(payload.subdomain or payload.slug).strip().lower(),
        business_type=payload.business_type,
        modules=",".join(payload.modules),
    )
    session.add(ten)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="El slug, el dominio SIP o el subdominio ya existen")
    await session.refresh(ten)

    # Ajustes de la empresa (fs_domain sale de Tenant.sip_domain) y su
    # primer administrador. El nombre de usuario lleva el slug para seguir
    # siendo único en toda la plataforma.
    await get_or_create_settings(session, ten.id)
    password = secrets.token_urlsafe(12)
    session.add(
        User(
            username=f"admin.{ten.slug}",
            full_name=f"Administrador {ten.name}",
            tenant_id=ten.id,
            role=permissions.ADMIN,
            password_hash=hash_password(password),
            enabled=True,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="No se pudo crear el administrador de la empresa")
    out = await _out(session, ten)
    return TenantCreatedOut(
        **out.model_dump(),
        admin_username=f"admin.{ten.slug}",
        admin_password=password,
    )


@router.put("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: int, payload: TenantUpdate, session: AsyncSession = Depends(get_admin_session)
):
    ten = await session.get(Tenant, tenant_id)
    if not ten:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "modules" and value is not None:
            setattr(ten, "modules", ",".join(value))
        else:
            setattr(ten, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="El dominio SIP ya lo usa otra empresa")
    await session.refresh(ten)
    return await _out(session, ten)


@router.get("/{tenant_id}/licencia", response_model=LicenseOut)
async def get_licencia(tenant_id: int, session: AsyncSession = Depends(get_admin_session)):
    ten = await session.get(Tenant, tenant_id)
    if not ten:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    lic = await licensing.obtener(session, tenant_id)
    return await _lic_out(session, lic)


@router.put("/{tenant_id}/licencia", response_model=LicenseOut)
async def update_licencia(
    tenant_id: int, payload: LicenseUpdate, session: AsyncSession = Depends(get_admin_session)
):
    """Define el plan, estado y límites de la licencia de una empresa. Al
    cambiar de plan, los límites por defecto del nuevo plan se aplican
    salvo que estén sobreescritos en la licencia."""
    ten = await session.get(Tenant, tenant_id)
    if not ten:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    lic = await licensing.obtener(session, tenant_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lic, field, value)
    await session.commit()
    await session.refresh(lic)
    return await _lic_out(session, lic)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(tenant_id: int, session: AsyncSession = Depends(get_admin_session)):
    ten = await session.get(Tenant, tenant_id)
    if not ten:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if ten.id == 1:
        raise HTTPException(status_code=400, detail="No se puede eliminar la empresa inicial")
    await session.delete(ten)
    await session.commit()
