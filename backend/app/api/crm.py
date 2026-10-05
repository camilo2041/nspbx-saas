"""CRM: contactos, su ficha con el historial, notas, campos propios, lista de
no llamar e importación de CSV (docs/plan-contact-center.md, fase 2).

Ver exige `crm:ver`; crear, editar, importar, los campos propios y la lista
de no llamar, `crm:gestionar`. La ficha muestra cada parte del historial
solo si el usuario puede verla por su lado: las llamadas con
`llamadas:ver_todas`, las campañas y la cobranza con `campanas:gestionar`, las
citas con `citas:gestionar`. Así un rol personalizado con CRM no ve por acá
lo que no podría ver en su pantalla.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions
from app.core.auth import requiere, usuario_actual
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import (
    Appointment,
    CallLog,
    Campaign,
    CampaignNumber,
    CampoContacto,
    Contacto,
    Debt,
    NoLlamar,
    Nota,
    PaymentPromise,
    Tenant,
    User,
)
from app.schemas import (
    CampoContactoIn,
    CampoContactoUpdate,
    ContactoIn,
    ContactoUpdate,
    NoLlamarIn,
    NotaIn,
)
from app.services import crm, importar_crm

router = APIRouter(prefix="/api/crm", tags=["crm"])

_GESTIONAR = Depends(requiere(permissions.CRM_GESTIONAR))


def _empresa(session: AsyncSession) -> int:
    tid = tenant_de_sesion(session)
    if tid is None:
        raise HTTPException(status_code=403, detail="El CRM es de cada empresa")
    return tid


def _contacto_out(c: Contacto, no_llamar: bool = False) -> dict:
    return {
        "id": c.id,
        "nombre": c.nombre,
        "documento": c.documento,
        "telefono": c.telefono,
        "telefonos": c.telefonos or [],
        "email": c.email,
        "direccion": c.direccion,
        "ciudad": c.ciudad,
        "campos": c.campos or {},
        "fuente": c.fuente,
        "no_llamar": no_llamar,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


async def _claves_en_no_llamar(session: AsyncSession, claves: set[str]) -> set[str]:
    if not claves:
        return set()
    return set(
        (
            await session.execute(
                select(NoLlamar.telefono_clave).where(NoLlamar.telefono_clave.in_(claves), crm.vigente_no_llamar())
            )
        ).scalars()
    )


# --- Contactos ------------------------------------------------------------------


@router.get("/contactos")
async def listar_contactos(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    query = select(Contacto)
    if q and q.strip():
        texto = q.strip()
        like = f"%{texto}%"
        condiciones = [Contacto.nombre.ilike(like), Contacto.documento.ilike(like), Contacto.email.ilike(like)]
        clave = crm.clave_telefono(texto)
        if len(clave) >= 4:
            condiciones.append(Contacto.telefono_clave.like(f"%{clave}%"))
        query = query.where(or_(*condiciones))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    filas = (
        await session.execute(
            query.order_by(desc(Contacto.updated_at), desc(Contacto.id)).limit(min(max(limit, 1), 200)).offset(max(0, offset))
        )
    ).scalars().all()
    bloqueadas = await _claves_en_no_llamar(session, {c.telefono_clave for c in filas})
    return {"total": total, "contactos": [_contacto_out(c, c.telefono_clave in bloqueadas) for c in filas]}


async def _aplicar(session: AsyncSession, contacto: Contacto, cambios: dict) -> None:
    if "campos" in cambios:
        defs = await crm.definiciones(session)
        try:
            contacto.campos = crm.validar_campos(defs, cambios.pop("campos")) or None
        except ValueError as exc:
            raise crm.error_422(str(exc)) from None
    if "telefono" in cambios and cambios["telefono"]:
        clave = crm.clave_telefono(cambios["telefono"])
        if not clave:
            raise crm.error_422("El teléfono necesita dígitos")
        contacto.telefono_clave = clave
    if "telefonos" in cambios:
        cambios["telefonos"] = [t for t in (cambios["telefonos"] or [])]
    for campo, valor in cambios.items():
        if campo == "documento" and valor is not None:
            valor = valor.strip() or None
        setattr(contacto, campo, valor)


async def _sin_duplicado(session: AsyncSession, contacto: Contacto) -> None:
    otro = (
        await session.execute(
            select(Contacto.id).where(Contacto.telefono_clave == contacto.telefono_clave, Contacto.id != (contacto.id or 0))
        )
    ).scalars().first()
    if otro:
        raise HTTPException(status_code=409, detail={"mensaje": "Ya hay un contacto con ese teléfono", "contacto_id": otro})


@router.post("/contactos", status_code=status.HTTP_201_CREATED, dependencies=[_GESTIONAR])
async def crear_contacto(payload: ContactoIn, session: AsyncSession = Depends(get_session)):
    tid = _empresa(session)
    contacto = Contacto(tenant_id=tid, fuente="manual", nombre="", telefono=payload.telefono, telefono_clave="")
    await _aplicar(session, contacto, payload.model_dump(mode="json"))
    await _sin_duplicado(session, contacto)
    session.add(contacto)
    await session.commit()
    bloqueadas = await _claves_en_no_llamar(session, {contacto.telefono_clave})
    return _contacto_out(contacto, bool(bloqueadas))


@router.get("/contactos/{contacto_id}")
async def ficha(
    contacto_id: int,
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    """El contacto y todo lo que hay de él, por cualquiera de sus teléfonos."""
    contacto = await traer_propio(session, Contacto, contacto_id)
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    def puede(permiso: str) -> bool:
        return permissions.puede(usuario.role, permiso, usuario.tenant_id)

    claves = {crm.clave_telefono(t) for t in crm.telefonos_de(contacto)} - {""}
    bloqueadas = await _claves_en_no_llamar(session, claves)
    defs = await crm.definiciones(session)
    notas = (
        await session.execute(
            select(Nota).where(Nota.contacto_id == contacto.id).order_by(desc(Nota.created_at), desc(Nota.id)).limit(200)
        )
    ).scalars().all()
    resultado = {
        "contacto": _contacto_out(contacto, contacto.telefono_clave in bloqueadas),
        "telefonos_no_llamar": sorted(bloqueadas),
        "campos_definidos": [_campo_out(c) for c in defs.values()],
        "notas": [
            {"id": n.id, "texto": n.texto, "autor": n.autor, "created_at": n.created_at} for n in notas
        ],
        "secciones": {
            "llamadas": puede(permissions.LLAMADAS_VER_TODAS),
            "campanas": puede(permissions.CAMPANAS_GESTIONAR),
            "cobranza": puede(permissions.CAMPANAS_GESTIONAR),
            "citas": puede(permissions.CITAS_GESTIONAR),
        },
        "llamadas": [],
        "campanas": [],
        "deudas": [],
        "promesas": [],
        "citas": [],
    }

    if resultado["secciones"]["llamadas"]:
        cond = crm.condicion_historial([CallLog.caller_number, CallLog.callee_number], contacto)
        if cond is not None:
            llamadas = (
                await session.execute(
                    select(CallLog).where(cond).order_by(desc(CallLog.started_at), desc(CallLog.id)).limit(50)
                )
            ).scalars().all()
            resultado["llamadas"] = [
                {
                    "id": c.id,
                    "direction": c.direction,
                    "status": c.status,
                    "caller_number": c.caller_number,
                    "callee_number": c.callee_number,
                    "billsec": c.billsec,
                    "ring_ms": c.ring_ms,
                    "started_at": c.started_at,
                    "tiene_grabacion": bool(c.recording_path),
                }
                for c in llamadas
            ]

    if resultado["secciones"]["campanas"]:
        filas = (
            await session.execute(
                select(CampaignNumber, Campaign.name)
                .join(Campaign, Campaign.id == CampaignNumber.campaign_id)
                .where(CampaignNumber.contacto_id == contacto.id)
                .order_by(desc(CampaignNumber.id))
                .limit(50)
            )
        ).all()
        resultado["campanas"] = [
            {
                "numero_id": n.id,
                "campaign_id": n.campaign_id,
                "campana": nombre,
                "phone": n.phone,
                "status": n.status,
                "attempts": n.attempts,
                "last_error": n.last_error,
                "ultimo_intento_at": n.ultimo_intento_at,
                "proximo_intento_at": n.proximo_intento_at,
            }
            for n, nombre in filas
        ]

    if resultado["secciones"]["cobranza"]:
        cond = crm.condicion_historial([Debt.phone], contacto)
        if cond is not None:
            deudas = (await session.execute(select(Debt).where(cond).order_by(desc(Debt.id)).limit(50))).scalars().all()
            resultado["deudas"] = [
                {"id": d.id, "amount": d.amount, "due_date": d.due_date, "status": d.status,
                 "invoice_number": d.invoice_number}
                for d in deudas
            ]
        cond = crm.condicion_historial([PaymentPromise.phone], contacto)
        if cond is not None:
            promesas = (
                await session.execute(select(PaymentPromise).where(cond).order_by(desc(PaymentPromise.id)).limit(50))
            ).scalars().all()
            resultado["promesas"] = [
                {"id": p.id, "amount_promised": p.amount_promised, "promise_date": p.promise_date,
                 "plan": p.plan, "status": p.status}
                for p in promesas
            ]

    if resultado["secciones"]["citas"]:
        cond = crm.condicion_historial([Appointment.phone], contacto)
        if cond is not None:
            citas = (
                await session.execute(
                    select(Appointment).where(cond).order_by(desc(Appointment.appointment_date)).limit(50)
                )
            ).scalars().all()
            resultado["citas"] = [
                {"id": a.id, "appointment_date": a.appointment_date, "status": a.status, "patient_name": a.patient_name}
                for a in citas
            ]
    return resultado


@router.put("/contactos/{contacto_id}", dependencies=[_GESTIONAR])
async def editar_contacto(contacto_id: int, payload: ContactoUpdate, session: AsyncSession = Depends(get_session)):
    contacto = await traer_propio(session, Contacto, contacto_id)
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    await _aplicar(session, contacto, payload.model_dump(mode="json", exclude_unset=True))
    await _sin_duplicado(session, contacto)
    await session.commit()
    bloqueadas = await _claves_en_no_llamar(session, {contacto.telefono_clave})
    return _contacto_out(contacto, bool(bloqueadas))


@router.delete("/contactos/{contacto_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_GESTIONAR])
async def borrar_contacto(contacto_id: int, session: AsyncSession = Depends(get_session)):
    """Borra el contacto y sus notas. Sus números en campañas se quedan (el
    historial de la campaña no se reescribe), ya sin contacto."""
    contacto = await traer_propio(session, Contacto, contacto_id)
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    await session.execute(
        update(CampaignNumber).where(CampaignNumber.contacto_id == contacto.id).values(contacto_id=None)
    )
    await session.execute(delete(Nota).where(Nota.contacto_id == contacto.id))
    await session.delete(contacto)
    await session.commit()


@router.post("/contactos/{contacto_id}/notas", status_code=status.HTTP_201_CREATED)
async def agregar_nota(
    contacto_id: int,
    payload: NotaIn,
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    contacto = await traer_propio(session, Contacto, contacto_id)
    if not contacto:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    nota = Nota(
        tenant_id=contacto.tenant_id,
        contacto_id=contacto.id,
        user_id=usuario.id,
        autor=usuario.full_name or usuario.username,
        texto=payload.texto.strip(),
    )
    session.add(nota)
    contacto.updated_at = datetime.utcnow()
    await session.commit()
    return {"id": nota.id, "texto": nota.texto, "autor": nota.autor, "created_at": nota.created_at}


# --- Campos propios ---------------------------------------------------------------


def _campo_out(c: CampoContacto) -> dict:
    return {
        "id": c.id,
        "clave": c.clave,
        "nombre": c.nombre,
        "tipo": c.tipo,
        "opciones": c.opciones or [],
        "obligatorio": c.obligatorio,
        "visible_agente": c.visible_agente,
        "orden": c.orden,
    }


@router.get("/campos")
async def listar_campos(session: AsyncSession = Depends(get_session)):
    return [_campo_out(c) for c in (await crm.definiciones(session)).values()]


@router.post("/campos", status_code=status.HTTP_201_CREATED, dependencies=[_GESTIONAR])
async def crear_campo(payload: CampoContactoIn, session: AsyncSession = Depends(get_session)):
    if (await session.execute(select(CampoContacto.id).where(CampoContacto.clave == payload.clave))).first():
        raise HTTPException(status_code=409, detail="Ya existe un campo con esa clave")
    campo = CampoContacto(tenant_id=_empresa(session), **payload.model_dump())
    session.add(campo)
    await session.commit()
    return _campo_out(campo)


@router.put("/campos/{campo_id}", dependencies=[_GESTIONAR])
async def editar_campo(campo_id: int, payload: CampoContactoUpdate, session: AsyncSession = Depends(get_session)):
    """La clave no cambia: es con la que están guardados los valores."""
    campo = await traer_propio(session, CampoContacto, campo_id)
    if not campo:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    for nombre, valor in payload.model_dump(exclude_unset=True).items():
        setattr(campo, nombre, valor)
    if campo.tipo == "opciones" and not campo.opciones:
        raise crm.error_422("Un campo de opciones necesita al menos una opción")
    await session.commit()
    return _campo_out(campo)


@router.delete("/campos/{campo_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_GESTIONAR])
async def borrar_campo(campo_id: int, session: AsyncSession = Depends(get_session)):
    """Deja de pedirse y de mostrarse. Los valores guardados se van con la
    próxima edición de cada contacto."""
    campo = await traer_propio(session, CampoContacto, campo_id)
    if not campo:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    await session.delete(campo)
    await session.commit()


# --- No llamar --------------------------------------------------------------------


def _no_llamar_out(r: NoLlamar) -> dict:
    return {
        "id": r.id,
        "telefono": r.telefono,
        "motivo": r.motivo,
        "hasta": r.hasta,
        "creado_por": r.creado_por,
        "created_at": r.created_at,
        "vigente": r.hasta is None or r.hasta > datetime.utcnow(),
    }


@router.get("/no-llamar")
async def listar_no_llamar(
    q: str | None = None, limit: int = 100, offset: int = 0, session: AsyncSession = Depends(get_session)
):
    query = select(NoLlamar)
    if q and crm.clave_telefono(q):
        query = query.where(NoLlamar.telefono_clave.like(f"%{crm.clave_telefono(q)}%"))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    filas = (
        await session.execute(query.order_by(desc(NoLlamar.id)).limit(min(max(limit, 1), 500)).offset(max(0, offset)))
    ).scalars().all()
    return {"total": total, "registros": [_no_llamar_out(r) for r in filas]}


@router.post("/no-llamar", status_code=status.HTTP_201_CREATED, dependencies=[_GESTIONAR])
async def agregar_no_llamar(
    payload: NoLlamarIn, session: AsyncSession = Depends(get_session), usuario: User = Depends(usuario_actual)
):
    """Si el número ya estaba, se actualizan el motivo y la vigencia."""
    clave = crm.clave_telefono(payload.telefono)
    if not clave:
        raise crm.error_422("El teléfono necesita dígitos")
    registro = (await session.execute(select(NoLlamar).where(NoLlamar.telefono_clave == clave))).scalar_one_or_none()
    if registro is None:
        registro = NoLlamar(tenant_id=_empresa(session), telefono=payload.telefono, telefono_clave=clave)
        session.add(registro)
    registro.motivo = payload.motivo
    registro.hasta = payload.hasta.replace(tzinfo=None) if payload.hasta else None
    registro.creado_por = usuario.full_name or usuario.username
    from app.services import integraciones

    await integraciones.emitir_seguro(session, _empresa(session), "lead.no_llamar", {
        "telefono": registro.telefono, "motivo": registro.motivo, "origen": "panel", "por": registro.creado_por,
    })
    await session.commit()
    return _no_llamar_out(registro)


@router.delete("/no-llamar/{no_llamar_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_GESTIONAR])
async def quitar_no_llamar(no_llamar_id: int, session: AsyncSession = Depends(get_session)):
    """Quitar un número de la lista no reactiva solo los que el marcador ya
    pasó a `no_llamar`: eso se hace desde la campaña («Reintentar» no los
    toca) para que sea una decisión explícita."""
    registro = await traer_propio(session, NoLlamar, no_llamar_id)
    if not registro:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    await session.delete(registro)
    await session.commit()


# --- Importar ---------------------------------------------------------------------------


@router.post("/importar/vista-previa", dependencies=[_GESTIONAR])
async def vista_previa(archivo: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    """Columnas, las primeras filas y un mapeo sugerido, sin guardar nada."""
    try:
        datos = importar_crm.leer(await archivo.read(importar_crm.MAX_BYTES + 1))
    except importar_crm.ErrorDeArchivo as exc:
        raise crm.error_422(str(exc)) from None
    claves = list((await crm.definiciones(session)).keys())
    return {
        "columnas": datos.columnas,
        "filas": datos.filas[:5],
        "total_filas": len(datos.filas),
        "sugerido": importar_crm.sugerir_mapeo(datos.columnas, claves),
    }


@router.post("/importar", dependencies=[_GESTIONAR])
async def importar(
    archivo: UploadFile = File(...),
    mapeo: str = Form(...),
    campaign_id: int | None = Form(default=None),
    nombre_lista: str | None = Form(default=None, max_length=120),
    session: AsyncSession = Depends(get_session),
    usuario: User = Depends(usuario_actual),
):
    """Crea o actualiza contactos. Con `campaign_id`, además los carga en
    esa campaña como una lista nueva (exige también gestionar campañas y el
    módulo de voizbot, como la carga manual)."""
    tid = _empresa(session)
    campana = None
    if campaign_id is not None:
        if not permissions.puede(usuario.role, permissions.CAMPANAS_GESTIONAR, usuario.tenant_id):
            raise HTTPException(status_code=403, detail="Tu rol no puede cargar números en campañas")
        empresa = await session.get(Tenant, tid)
        if not empresa or not empresa.has_module("voicebot"):
            raise HTTPException(status_code=403, detail="Tu empresa no tiene este módulo activo")
        campana = await traer_propio(session, Campaign, campaign_id)
        if not campana:
            raise HTTPException(status_code=404, detail="Campaña no encontrada")
    try:
        mapeo_dict = json.loads(mapeo)
        if not isinstance(mapeo_dict, dict) or not all(isinstance(v, str) for v in mapeo_dict.values()):
            raise ValueError
    except ValueError:
        raise crm.error_422("El mapeo tiene que ser un objeto {columna: destino}") from None
    try:
        datos = importar_crm.leer(await archivo.read(importar_crm.MAX_BYTES + 1))
        claves = set((await crm.definiciones(session)).keys())
        por_indice = importar_crm.validar_mapeo(mapeo_dict, datos.columnas, claves)
    except importar_crm.ErrorDeArchivo as exc:
        raise crm.error_422(str(exc)) from None

    reporte = await importar_crm.importar(session, tid, datos, por_indice, fuente="csv")
    carga = None
    if campana is not None and reporte.para_campana:
        from app.api.campaigns import cargar_numeros

        carga = await cargar_numeros(
            session, campana, reporte.para_campana, origen="csv",
            nombre_lista=nombre_lista or (archivo.filename or "CSV")[:120],
        )
    await session.commit()
    return {
        "filas": reporte.filas,
        "creados": reporte.creados,
        "actualizados": reporte.actualizados,
        "con_error": reporte.total_errores,
        "errores": reporte.errores,
        "campana": carga,
    }
