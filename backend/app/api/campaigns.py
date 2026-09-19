import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_session, tenant_de_sesion
from app.models import Appointment, Campaign, CampaignNumber, Debt, Trunk, VoiceBot
from app.schemas import (
    CampaignCreate,
    CampaignNumberIn,
    CampaignNumberUpdate,
    CampaignOut,
    CampaignStats,
    CampaignUpdate,
)
from app.services import licensing
from app.services.appointments import is_slot_free
from app.services.fechas import parse_fecha_hora as _parse_fecha_hora
from app.workers.dialer import dialer

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


async def _sincronizar_agenda(
    session: AsyncSession, phone: str, variables: dict[str, str]
) -> tuple[int | None, str | None]:
    """Si el número trae "cliente" y "fecha", carga/actualiza esa cita en
    la Agenda — es lo que hace que confirmar_cita/reagendar_cita tengan
    algo real sobre qué actuar durante la llamada, no solo el saludo.
    Devuelve (id_de_la_cita, None) si se cargó bien, o (None, motivo) si
    no se pudo. El id se le pasa al voizbot al marcar (ver
    workers/dialer.py) para que actúe sobre ESA cita puntual — sin esto
    tenía que adivinar por teléfono cuál era, y falla de verdad cuando el
    mismo número tiene más de una cita confirmada a la vez."""
    claves = {k.lower(): v for k, v in variables.items()}
    cliente = claves.get("cliente")
    fecha_raw = claves.get("fecha")
    if not cliente or not fecha_raw:
        return None, None  # esta fila no trae agenda, solo variables de saludo — no es un error
    fecha = _parse_fecha_hora(fecha_raw)
    if not fecha:
        return None, f'"{fecha_raw}" no se pudo leer como fecha y hora (formato: AAAA-MM-DD HH:MM)'

    # Se busca por teléfono (caso normal) O por nombre+fecha: la campaña
    # a veces marca a un teléfono de prueba distinto al de la cita real
    # (para probar la llamada sin timbrarle al paciente) pero con el
    # mismo "cliente"/"fecha" — si solo se buscara por teléfono, no
    # reconocería que es la MISMA cita y la bloquearía más abajo como
    # "horario ocupado" por chocar con la cita real de otro teléfono.
    # OJO: no se toca existente.phone acá — el de la cita real se
    # conserva, así find_next_appointment sigue funcionando si el
    # paciente real llama por su cuenta.
    existente = (
        await session.execute(
            select(Appointment).where(
                Appointment.appointment_date == fecha,
                (Appointment.phone == phone) | (func.lower(Appointment.patient_name) == cliente.lower()),
            )
        )
    ).scalar_one_or_none()
    if existente:
        existente.patient_name = cliente
        existente.status = "confirmed"
        return existente.id, None

    if not await is_slot_free(session, fecha, 30):
        return None, f"el horario {fecha:%Y-%m-%d %H:%M} ya está ocupado por otra cita"

    nueva = Appointment(patient_name=cliente, phone=phone, appointment_date=fecha, status="confirmed")
    session.add(nueva)
    await session.flush()  # para conocer nueva.id sin esperar al commit del lote
    return nueva.id, None


async def _sincronizar_deuda(
    session: AsyncSession, phone: str, variables: dict[str, str]
) -> tuple[int | None, str | None]:
    """Si el número trae "cliente" y "monto" (campaña de cobranza), crea o
    actualiza la deuda de ese teléfono — es lo que le da al voizbot algo
    real sobre qué conversar durante la llamada (monto, vencimiento,
    factura). Devuelve (id_de_la_deuda, None) o (None, motivo)."""
    claves = {k.lower(): v for k, v in variables.items()}
    cliente = claves.get("cliente")
    monto_raw = claves.get("monto")
    if not cliente or not monto_raw:
        return None, None  # esta fila no trae deuda, solo variables de saludo — no es un error
    try:
        monto = float(str(monto_raw).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None, f'"{monto_raw}" no se pudo leer como monto'

    due_date = None
    if claves.get("vencimiento"):
        due_date = _parse_fecha_hora(claves["vencimiento"])
        if not due_date:
            # El vencimiento suele cargarse solo con la fecha, sin hora; el
            # parser de agenda exige hora. Se acepta fecha sola también.
            try:
                from datetime import datetime

                due_date = datetime.strptime(claves["vencimiento"].strip(), "%Y-%m-%d")
            except ValueError:
                try:
                    due_date = datetime.strptime(claves["vencimiento"].strip().replace("/", "-"), "%d-%m-%Y")
                except ValueError:
                    due_date = None
        if not due_date:
            return None, f'"{claves["vencimiento"]}" no se pudo leer como fecha (formato: AAAA-MM-DD)'

    # La deuda se identifica por teléfono: es como la busca el voizbot al
    # contestar. Se actualiza la existente (se mantiene el id para no
    # romper promesas ya registradas contra la deuda vieja).
    existente = (
        await session.execute(
            select(Debt).where(
                (Debt.phone == phone) | (func.lower(Debt.debtor_name) == cliente.lower()),
            )
        )
    ).scalars().first()
    if existente:
        existente.debtor_name = cliente
        existente.amount = monto
        existente.due_date = due_date
        if claves.get("factura"):
            existente.invoice_number = claves["factura"]
        existente.status = "open"
        return existente.id, None

    deuda = Debt(
        phone=phone,
        debtor_name=cliente,
        amount=monto,
        due_date=due_date,
        invoice_number=claves.get("factura"),
        status="open",
    )
    session.add(deuda)
    await session.flush()  # para conocer deuda.id sin esperar al commit del lote
    return deuda.id, None


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Campaign).options(selectinload(Campaign.trunk), selectinload(Campaign.voicebot)).order_by(Campaign.id)
    )
    return result.scalars().all()


@router.get("/list/detail")
async def list_campaigns_detail(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Campaign).options(selectinload(Campaign.trunk), selectinload(Campaign.voicebot)).order_by(Campaign.id)
    )
    campaigns = result.scalars().all()
    out = []
    for c in campaigns:
        res = await session.execute(
            select(CampaignNumber.status, func.count(CampaignNumber.id))
            .where(CampaignNumber.campaign_id == c.id)
            .group_by(CampaignNumber.status)
        )
        counts = dict(res.all())
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "trunk_id": c.trunk_id,
                "voicebot_id": c.voicebot_id,
                "max_concurrency": c.max_concurrency,
                "retries": c.retries,
                "message_template": c.message_template,
                "ai_intent": c.ai_intent,
                "status": c.status,
                "started_at": c.started_at,
                "finished_at": c.finished_at,
                "trunk_name": c.trunk.name if c.trunk else None,
                "voicebot_name": c.voicebot.name if c.voicebot else None,
                "stats": {
                    "total": sum(counts.values()),
                    "pending": counts.get("pending", 0),
                    "dialing": counts.get("dialing", 0),
                    "answered": counts.get("answered", 0),
                    "busy": counts.get("busy", 0),
                    "noanswer": counts.get("noanswer", 0),
                    "failed": counts.get("failed", 0),
                    "done": counts.get("done", 0),
                    "active_calls": counts.get("dialing", 0),
                },
            }
        )
    return out


async def _validar_referencias(session: AsyncSession, trunk_id: int | None, voicebot_id: int | None) -> None:
    """La troncal y el voizbot tienen que ser de ESTA empresa. `session.get` va
    por la sesión atada a la empresa, que no ve las ajenas; sin esta comprobación
    un id adivinado apuntaba a la troncal de otra (la FK no distingue empresas)."""
    if trunk_id and not await session.get(Trunk, trunk_id):
        raise HTTPException(status_code=400, detail="Troncal inexistente")
    if voicebot_id and not await session.get(VoiceBot, voicebot_id):
        raise HTTPException(status_code=400, detail="Voizbot inexistente")


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate, session: AsyncSession = Depends(get_session)):
    tid = tenant_de_sesion(session)
    if tid is not None:
        lic = await licensing.obtener(session, tid)
        if not await licensing.hay_cupo(session, lic, "max_campaigns", await licensing.contar_campanas(session, tid)):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Alcanzaste el límite de campañas de tu plan. Mejora la licencia para crear más.",
            )
    await _validar_referencias(session, payload.trunk_id, payload.voicebot_id)
    campaign = Campaign(**payload.model_dump())
    session.add(campaign)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Nombre de campaña duplicado")
    await session.refresh(campaign)
    return campaign


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    return campaign


@router.put("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int, payload: CampaignUpdate, session: AsyncSession = Depends(get_session)
):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    cambios = payload.model_dump(exclude_unset=True)
    await _validar_referencias(session, cambios.get("trunk_id"), cambios.get("voicebot_id"))
    for field, value in cambios.items():
        setattr(campaign, field, value)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    await session.delete(campaign)
    await session.commit()


def _number_out(n: CampaignNumber) -> dict:
    return {
        "id": n.id,
        "campaign_id": n.campaign_id,
        "phone": n.phone,
        "status": n.status,
        "attempts": n.attempts,
        "last_error": n.last_error,
        "vars": json.loads(n.extra_data) if n.extra_data else {},
        "created_at": n.created_at,
    }


@router.post("/{campaign_id}/numbers", status_code=status.HTTP_201_CREATED)
async def add_numbers(
    campaign_id: int, payload: CampaignNumberIn, session: AsyncSession = Depends(get_session)
):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    res = await session.execute(
        select(CampaignNumber).where(CampaignNumber.campaign_id == campaign_id)
    )
    existentes = {n.phone: n for n in res.scalars().all()}
    es_cobranza = (campaign.ai_intent or "").strip().lower() == "cobranza"
    added = 0
    updated = 0
    agenda_creadas = 0
    agenda_omitidas: list[dict] = []
    for fila in payload.numbers:
        numero = existentes.get(fila.phone)
        if numero:
            # Ya estaba cargado en esta campaña. Antes esto se ignoraba
            # en silencio — si alguien volvía a pegar el mismo número
            # para corregir un dato mal cargado, la corrección nunca
            # llegaba a guardarse y no había ningún aviso de que pasó
            # eso. Ahora, si esta vez trae variables, se actualizan.
            if fila.vars:
                numero.extra_data = json.dumps(fila.vars, ensure_ascii=False)
                updated += 1
        else:
            numero = CampaignNumber(
                campaign_id=campaign_id,
                phone=fila.phone,
                extra_data=json.dumps(fila.vars, ensure_ascii=False) if fila.vars else None,
            )
            session.add(numero)
            existentes[fila.phone] = numero
            added += 1
        if fila.vars:
            if es_cobranza:
                deuda_id, motivo = await _sincronizar_deuda(session, fila.phone, fila.vars)
                if motivo:
                    agenda_omitidas.append({"phone": fila.phone, "motivo": motivo})
            else:
                appointment_id, motivo = await _sincronizar_agenda(session, fila.phone, fila.vars)
                if motivo:
                    agenda_omitidas.append({"phone": fila.phone, "motivo": motivo})
                elif appointment_id:
                    numero.appointment_id = appointment_id
                    agenda_creadas += 1
    await session.commit()
    return {
        "added": added,
        "updated": updated,
        "total": len(existentes),
        "agenda_creadas": agenda_creadas,
        "agenda_omitidas": agenda_omitidas,
    }


@router.get("/{campaign_id}/numbers")
async def list_numbers(
    campaign_id: int,
    search: str | None = None,
    estado: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Paginado y con filtros: una campaña de marcación masiva puede
    tener miles de números cargados, y antes se devolvían TODOS en cada
    apertura del detalle — con el navegador dibujando la lista entera.
    El filtro por estado es lo que hace usable revisar "cuáles fallaron"
    sin tener que recorrer la lista completa a ojo."""
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    query = select(CampaignNumber).where(CampaignNumber.campaign_id == campaign_id)
    if search:
        like = f"%{search.strip()}%"
        # extra_data guarda las variables (nombre, fecha...) como JSON en
        # texto, así que buscar ahí adentro permite encontrar por nombre
        # de paciente y no solo por teléfono.
        query = query.where((CampaignNumber.phone.ilike(like)) | (CampaignNumber.extra_data.ilike(like)))
    if estado:
        query = query.where(CampaignNumber.status == estado)
    query = query.order_by(CampaignNumber.id).limit(min(limit, 500)).offset(max(0, offset))
    res = await session.execute(query)
    return [_number_out(n) for n in res.scalars().all()]


@router.put("/{campaign_id}/numbers/{number_id}")
async def update_number(
    campaign_id: int, number_id: int, payload: CampaignNumberUpdate, session: AsyncSession = Depends(get_session)
):
    number = await session.get(CampaignNumber, number_id)
    if not number or number.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Número no encontrado")
    number.phone = payload.phone
    if payload.vars is not None:
        number.extra_data = json.dumps(payload.vars, ensure_ascii=False) if payload.vars else None
    await session.commit()
    await session.refresh(number)
    return _number_out(number)


@router.delete("/{campaign_id}/numbers/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_number(campaign_id: int, number_id: int, session: AsyncSession = Depends(get_session)):
    number = await session.get(CampaignNumber, number_id)
    if not number or number.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="Número no encontrado")
    await session.delete(number)
    await session.commit()


@router.delete("/{campaign_id}/numbers")
async def clear_numbers(campaign_id: int, session: AsyncSession = Depends(get_session)):
    """Vacía toda la lista de números ya cargados — para volver a empezar
    sin borrarlos uno por uno. No toca las citas que se hayan
    sincronizado en la Agenda a partir de ellos, esas quedan igual."""
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    if campaign.status == "running":
        raise HTTPException(status_code=400, detail="Detené la campaña antes de vaciar sus números")
    result = await session.execute(delete(CampaignNumber).where(CampaignNumber.campaign_id == campaign_id))
    await session.commit()
    return {"deleted": result.rowcount}


@router.get("/{campaign_id}/stats", response_model=CampaignStats)
async def campaign_stats(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    res = await session.execute(
        select(CampaignNumber.status, func.count(CampaignNumber.id))
        .where(CampaignNumber.campaign_id == campaign_id)
        .group_by(CampaignNumber.status)
    )
    counts = dict(res.all())
    stats = CampaignStats(
        total=sum(counts.values()),
        pending=counts.get("pending", 0),
        dialing=counts.get("dialing", 0),
        answered=counts.get("answered", 0),
        busy=counts.get("busy", 0),
        noanswer=counts.get("noanswer", 0),
        failed=counts.get("failed", 0),
        done=counts.get("done", 0),
        active_calls=counts.get("dialing", 0),
    )
    return stats


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    res = await session.execute(
        select(CampaignNumber)
        .where(CampaignNumber.campaign_id == campaign_id, CampaignNumber.status == "pending")
        .limit(1)
    )
    if not res.first():
        raise HTTPException(status_code=400, detail="No hay números pendientes")
    campaign.status = "running"
    campaign.started_at = datetime.utcnow()
    campaign.finished_at = None
    await session.commit()
    dialer.start()
    return {"ok": True, "status": "running"}


@router.post("/{campaign_id}/retry")
async def retry_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    """Vuelve a poner en 'pending' los números fallidos o completados, para
    poder relanzar la campaña (ej. tras corregir la troncal o el voizbot)."""
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    result = await session.execute(
        update(CampaignNumber)
        .where(
            CampaignNumber.campaign_id == campaign_id,
            CampaignNumber.status.in_(["failed", "done", "busy", "noanswer"]),
        )
        .values(status="pending", attempts=0, last_error=None)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=400, detail="No hay números para reintentar")
    campaign.status = "idle"
    campaign.finished_at = None
    await session.commit()
    return {"ok": True, "reset": result.rowcount}


@router.post("/{campaign_id}/stop")
async def stop_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    campaign.status = "idle"
    await session.commit()
    return {"ok": True, "status": "idle"}
