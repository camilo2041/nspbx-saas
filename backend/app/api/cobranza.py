"""Cobranza: deudas y promesas de pago.

Las deudas son lo que el voizbot de cobranza consulta por teléfono al
contestar (ver app/services/ai_agent.py) y lo que la campaña de cobranza
carga al agregar números (ver app/api/campaigns.py). Las promesas de pago
son el resultado de cada llamada: la persona se comprometió a pagar X el
día Y.

Este router gestiona ambas a mano, además de lo que hacen la campaña y el
bot — la página de Cobranza del panel muestra deudas y promesas en vivo.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import filtro_empresa, get_session, traer_propio
from app.models import Debt, PaymentPromise
from app.schemas import DebtCreate, DebtOut, DebtUpdate, PaymentPromiseOut, PaymentPromiseUpdate

router = APIRouter(prefix="/api/cobranza", tags=["cobranza"])


@router.get("/debts", response_model=list[DebtOut])
async def list_debts(
    search: str | None = None,
    estado: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    query = select(Debt)
    if search:
        like = f"%{search.strip()}%"
        query = query.where((Debt.phone.ilike(like)) | (Debt.debtor_name.ilike(like)))
    if estado:
        query = query.where(Debt.status == estado)
    query = query.order_by(Debt.updated_at.desc()).limit(min(limit, 500)).offset(max(0, offset))
    return (await session.execute(query)).scalars().all()


@router.post("/debts", response_model=DebtOut, status_code=status.HTTP_201_CREATED)
async def create_debt(payload: DebtCreate, session: AsyncSession = Depends(get_session)):
    deuda = Debt(**payload.model_dump())
    session.add(deuda)
    await session.commit()
    await session.refresh(deuda)
    return deuda


@router.put("/debts/{debt_id}", response_model=DebtOut)
async def update_debt(debt_id: int, payload: DebtUpdate, session: AsyncSession = Depends(get_session)):
    deuda = await traer_propio(session, Debt, debt_id)
    if not deuda:
        raise HTTPException(status_code=404, detail="Deuda no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(deuda, field, value)
    await session.commit()
    await session.refresh(deuda)
    return deuda


@router.delete("/debts/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(debt_id: int, session: AsyncSession = Depends(get_session)):
    deuda = await traer_propio(session, Debt, debt_id)
    if not deuda:
        raise HTTPException(status_code=404, detail="Deuda no encontrada")
    await session.delete(deuda)
    await session.commit()


@router.get("/promises", response_model=list[PaymentPromiseOut])
async def list_promises(
    search: str | None = None,
    estado: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    query = select(PaymentPromise)
    if search:
        like = f"%{search.strip()}%"
        query = query.where((PaymentPromise.phone.ilike(like)) | (PaymentPromise.debtor_name.ilike(like)))
    if estado:
        query = query.where(PaymentPromise.status == estado)
    query = query.order_by(PaymentPromise.created_at.desc()).limit(min(limit, 500)).offset(max(0, offset))
    return (await session.execute(query)).scalars().all()


@router.put("/promises/{promise_id}", response_model=PaymentPromiseOut)
async def update_promise(promise_id: int, payload: PaymentPromiseUpdate, session: AsyncSession = Depends(get_session)):
    """Marcar la promesa como cumplida o incumplida según el cobro real.

    Cumplida no salda la deuda sola: un abono o una cuota cumplen la
    promesa y la deuda sigue. Eso se cambia en la deuda."""
    promesa = await traer_propio(session, PaymentPromise, promise_id)
    if not promesa:
        raise HTTPException(status_code=404, detail="Promesa no encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(promesa, field, value)
    await session.commit()
    await session.refresh(promesa)
    return promesa


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)):
    """Totales de la cartera: cuánto se debe, cuánto se prometió pagar y
    cuántas promesas están vigentes."""
    # Sumado en la base: antes se traía la cartera entera a Python (con
    # 100.000 deudas y otras tantas promesas, 3 s y casi 300 MB por petición).
    vigente = Debt.status.in_(("open", "promised", "overdue"))
    deudas = (await session.execute(
        select(
            func.count(Debt.id),
            func.count(case((Debt.status == "open", 1))),
            func.coalesce(func.sum(case((vigente, Debt.amount), else_=0)), 0),
        ).where(filtro_empresa(session, Debt))
    )).one()
    promesas = (await session.execute(
        select(
            func.count(PaymentPromise.id),
            func.count(case((PaymentPromise.status == "pending", 1))),
            func.coalesce(func.sum(PaymentPromise.amount_promised), 0),
        ).where(filtro_empresa(session, PaymentPromise))
    )).one()
    return {
        "debts_total": deudas[0],
        "debts_open": deudas[1],
        "amount_owed": round(float(deudas[2]), 2),
        "promises_total": promesas[0],
        "promises_pending": promesas[1],
        "amount_promised": round(float(promesas[2]), 2),
    }
