"""La ficha del cliente que aparece cuando suena o se contesta una llamada:
quién es (CRM), sus últimas notas y llamadas, y si está en «no llamar».

Busca por los últimos 10 dígitos del número (crm.clave_telefono), igual que
el resto del CRM: da igual si llega con +57, 57 o sin indicativo. Solo lo
necesario para atender; el detalle completo sigue en el CRM.
"""

from sqlalchemy import desc, or_, select

from app.core import permissions
from app.models import CallLog, Contacto, Nota, User
from app.services import crm

NOTAS = 3
LLAMADAS = 5


async def ficha(session, numero: str, usuario: User) -> dict:
    clave = crm.clave_telefono(numero)
    if len(clave) < 7:
        # Una extensión interna o un número oculto: no hay a quién buscar.
        return {"numero": numero, "contacto": None, "no_llamar": False, "notas": [], "llamadas": [], "puede_crm": False}
    contacto = (
        await session.execute(select(Contacto).where(Contacto.telefono_clave == clave).order_by(Contacto.id).limit(1))
    ).scalar_one_or_none()
    no_llamar = await crm.en_no_llamar(session, numero) is not None
    notas = []
    campos = []
    if contacto is not None:
        notas = [
            {"texto": n.texto, "autor": n.autor, "created_at": n.created_at}
            for n in (
                await session.execute(
                    select(Nota).where(Nota.contacto_id == contacto.id).order_by(desc(Nota.created_at), desc(Nota.id)).limit(NOTAS)
                )
            ).scalars()
        ]
        defs = await crm.definiciones(session)
        campos = [
            {"nombre": defs[k].nombre if k in defs else k, "valor": v}
            for k, v in (contacto.campos or {}).items()
            if v not in (None, "")
        ]
    llamadas = [
        {"started_at": c.started_at, "direccion": c.direction, "estado": c.status, "billsec": c.billsec,
         "cola": c.cola}
        for c in (
            await session.execute(
                select(CallLog)
                .where(or_(crm.clave_sql(CallLog.caller_number) == clave, crm.clave_sql(CallLog.callee_number) == clave))
                .order_by(desc(CallLog.started_at), desc(CallLog.id))
                .limit(LLAMADAS)
            )
        ).scalars()
    ]
    return {
        "numero": numero,
        "contacto": None if contacto is None else {
            "id": contacto.id, "nombre": contacto.nombre, "documento": contacto.documento,
            "email": contacto.email, "ciudad": contacto.ciudad, "campos": campos,
        },
        "no_llamar": no_llamar,
        "notas": notas,
        "llamadas": llamadas,
        "puede_crm": permissions.puede(usuario.role, permissions.CRM_VER, usuario.tenant_id),
    }
