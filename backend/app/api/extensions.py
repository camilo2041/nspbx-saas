from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validacion
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import Extension, Tenant, Trunk
from app.schemas import CallRequest, ExtensionCreate, ExtensionOut, ExtensionUpdate
from app.services import licensing
from app.services.config_generator import orden_troncales
from app.services import salientes
from app.services.esl import originate_bridge, reloadxml

router = APIRouter(prefix="/api/extensions", tags=["extensions"])


@router.get("", response_model=list[ExtensionOut])
async def list_extensions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Extension).order_by(Extension.number))
    return result.scalars().all()


def _clave_valida(clave: str | None, numero: str) -> str:
    """La contraseña SIP a guardar: la generada si viene vacía, o la dada
    si pasa la validación. Se exige al crear y al cambiarla; las que ya
    existían no se tocan (cambiarlas sin aviso desregistraría teléfonos)."""
    if not clave:
        return validacion.generar_clave_sip()
    problema = validacion.problema_clave_sip(clave, numero)
    if problema:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problema)
    return clave


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
    datos = payload.model_dump()
    datos["password"] = _clave_valida(datos.get("password"), datos["number"])
    ext = Extension(**datos)
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
    ext = await traer_propio(session, Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    return ext


@router.put("/{extension_id}", response_model=ExtensionOut)
async def update_extension(
    extension_id: int, payload: ExtensionUpdate, session: AsyncSession = Depends(get_session)
):
    ext = await traer_propio(session, Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    cambios = payload.model_dump(exclude_unset=True)
    if "password" in cambios:
        # Vacía o la misma = "no la toqué" (el panel manda el formulario
        # completo, con la contraseña actual): una extensión con una clave
        # débil heredada se puede seguir editando sin cambiarla.
        if cambios["password"] and cambios["password"] != ext.password:
            cambios["password"] = _clave_valida(cambios["password"], cambios.get("number") or ext.number)
        else:
            cambios.pop("password")
    # Desactivarla o cambiarle la clave (lo que se hace cuando se filtró)
    # tiene que sacar ya a quien la esté usando, no cuando venza su registro.
    cortar = (cambios.get("enabled") is False and ext.enabled) or "password" in cambios
    numero_anterior = ext.number
    for field, value in cambios.items():
        setattr(ext, field, value)
    await session.commit()
    await session.refresh(ext)
    if cortar:
        await _cortar(session, ext.tenant_id, numero_anterior)
    return ext


async def _cortar(session, tenant_id: int, numero: str) -> None:
    """Cuelga las salientes en curso de la extensión y tira su registro
    (services/emergencia.py). Si FreeSWITCH no responde, el cambio en la
    base vale igual: el directorio ya no la autentica con la clave vieja."""
    import logging

    from app.services import emergencia

    tenant = await session.get(Tenant, tenant_id)
    try:
        await emergencia.cortar_extension(numero, tenant.sip_domain)
    except Exception as exc:
        logging.getLogger(__name__).error("No se pudo cortar la extensión %s en FreeSWITCH: %s", numero, exc)


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(extension_id: int, session: AsyncSession = Depends(get_session)):
    ext = await traer_propio(session, Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    tenant_id, numero = ext.tenant_id, ext.number
    await session.delete(ext)
    await session.commit()
    await _cortar(session, tenant_id, numero)


@router.post("/{extension_id}/call")
async def call_extension(
    extension_id: int, payload: CallRequest, session: AsyncSession = Depends(get_session)
):
    """Click-to-call: hace sonar la extensión y, al contestar, la bridgea al destino
    (otra extensión interna, o un número externo vía la troncal indicada)."""
    ext = await traer_propio(session, Extension, extension_id)
    if not ext:
        raise HTTPException(status_code=404, detail="Extensión no encontrada")
    if not ext.enabled:
        raise HTTPException(status_code=400, detail="La extensión está deshabilitada")

    destination = payload.destination.strip()

    if payload.trunk_id is not None:
        trunk = await traer_propio(session, Trunk, payload.trunk_id)
        if not trunk:
            raise HTTPException(status_code=404, detail="Troncal no encontrada")
        if not trunk.enabled:
            raise HTTPException(status_code=400, detail="La troncal está deshabilitada")
        # Esto sale directo a la troncal (originate), sin pasar por el
        # dialplan: la política de salientes se aplica acá o no se aplica.
        politica = await salientes.politica_de(session, ext.tenant_id)
        motivo = salientes.motivo_bloqueo(destination, politica)
        if motivo:
            raise HTTPException(status_code=403, detail=motivo)
        # El mismo horario laboral que el dialplan (si la empresa lo usa).
        if politica.fuera_de_horario and ext.number not in politica.permitidas_fuera_de_horario:
            raise HTTPException(
                status_code=403,
                detail="Fuera del horario laboral de la empresa: esta extensión no tiene permiso para llamar afuera",
            )
        # El mismo tope de llamadas por segundo que el dialplan.
        try:
            salientes.exigir_ritmo(ext.tenant_id, politica.cps)
        except salientes.RitmoExcedido as e:
            raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": "1"})
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
        sale_por_troncal = True
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
        sale_por_troncal = False

    try:
        # El dominio de la EMPRESA de la extensión (el de su directorio en
        # FreeSWITCH), no una variable de proceso: con varias empresas cada
        # extensión vive en la suya.
        tenant = await session.get(Tenant, ext.tenant_id)
        dominio = tenant.sip_domain if tenant else "nspbx.local"
        # Marca de "sale por troncal" (ver services/emergencia.py): se puede
        # colgar en curso por empresa o por extensión.
        marcas = {"nspbx_saliente": str(ext.tenant_id), "nspbx_saliente_ext": f"{ext.number}@{dominio}"}
        out = await originate_bridge(
            from_endpoint=f"user/{ext.number}@{dominio}",
            bridge_target=bridge_target,
            caller_id=ext.caller_id_name or ext.number,
            variables=marcas if sale_por_troncal else None,
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
