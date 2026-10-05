"""Webhooks hacia el CRM de la empresa (services/integraciones.py).

Con `ajustes:gestionar`, como las claves de API: quien configura a dónde
salen los datos de la empresa es quien administra la empresa. El secreto de
firma se muestra una sola vez (al crear o rotar); después solo se guarda
cifrado.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.core.database import get_session, tenant_de_sesion, traer_propio
from app.models import EntregaWebhook, Webhook
from app.services import integraciones

router = APIRouter(prefix="/api/integraciones", tags=["integraciones"])

MAX_WEBHOOKS = 10


def _eventos(v: list[str]) -> list[str]:
    malos = [e for e in v if e not in integraciones.EVENTOS]
    if malos:
        raise ValueError(f"Eventos desconocidos: {', '.join(malos)}")
    if not v:
        raise ValueError("Elige al menos un evento")
    return sorted(set(v))


def _url(v: str) -> str:
    try:
        return urls.validar_url_https(v)
    except urls.UrlNoPermitida as exc:
        raise ValueError(str(exc))


class WebhookIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=80)
    url: str = Field(..., max_length=500)
    eventos: list[str] = Field(..., max_length=len(integraciones.EVENTOS))

    @field_validator("url")
    @classmethod
    def _v_url(cls, v: str) -> str:
        return _url(v)

    @field_validator("eventos")
    @classmethod
    def _v_eventos(cls, v: list[str]) -> list[str]:
        return _eventos(v)


class WebhookUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=500)
    eventos: list[str] | None = Field(default=None, max_length=len(integraciones.EVENTOS))
    activo: bool | None = None

    @field_validator("url")
    @classmethod
    def _v_url(cls, v: str | None) -> str | None:
        return _url(v) if v is not None else v

    @field_validator("eventos")
    @classmethod
    def _v_eventos(cls, v: list[str] | None) -> list[str] | None:
        return _eventos(v) if v is not None else v


def _out(w: Webhook, pendientes: int = 0) -> dict:
    return {
        "id": w.id, "nombre": w.nombre, "url": w.url, "eventos": w.eventos or [], "activo": w.activo,
        "fallos_seguidos": w.fallos_seguidos, "ultimo_ok_at": w.ultimo_ok_at, "created_at": w.created_at,
        "pendientes": pendientes,
    }


def _entrega_out(e: EntregaWebhook) -> dict:
    return {
        "id": e.id, "webhook_id": e.webhook_id, "evento": e.evento, "estado": e.estado, "intentos": e.intentos,
        "proximo_intento_at": e.proximo_intento_at, "ultimo_codigo": e.ultimo_codigo, "ultimo_error": e.ultimo_error,
        "entregado_at": e.entregado_at, "created_at": e.created_at,
    }


async def _webhook(session: AsyncSession, webhook_id: int) -> Webhook:
    w = await traer_propio(session, Webhook, webhook_id)
    if w is None:
        raise HTTPException(status_code=404, detail="Webhook no encontrado")
    return w


@router.get("/eventos")
async def eventos():
    return [{"evento": k, "descripcion": v} for k, v in integraciones.EVENTOS.items()]


@router.get("/webhooks")
async def listar(session: AsyncSession = Depends(get_session)):
    ganchos = (await session.execute(select(Webhook).order_by(Webhook.id))).scalars().all()
    pend = (
        await session.execute(select(EntregaWebhook.webhook_id).where(EntregaWebhook.estado == "pendiente"))
    ).scalars().all()
    return [_out(w, pend.count(w.id)) for w in ganchos]


@router.post("/webhooks", status_code=status.HTTP_201_CREATED)
async def crear(payload: WebhookIn, session: AsyncSession = Depends(get_session)):
    if len((await session.execute(select(Webhook.id))).all()) >= MAX_WEBHOOKS:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_WEBHOOKS} webhooks por empresa")
    secreto = integraciones.nuevo_secreto()
    w = Webhook(tenant_id=tenant_de_sesion(session), nombre=payload.nombre.strip(), url=payload.url, eventos=payload.eventos,
                secreto=secreto, activo=True)
    session.add(w)
    await session.commit()
    integraciones.invalidar_cache(w.tenant_id)
    return {**_out(w), "secreto": secreto}


@router.put("/webhooks/{webhook_id}")
async def editar(webhook_id: int, payload: WebhookUpdate, session: AsyncSession = Depends(get_session)):
    w = await _webhook(session, webhook_id)
    for clave, valor in payload.model_dump(exclude_none=True).items():
        setattr(w, clave, valor.strip() if isinstance(valor, str) else valor)
    if payload.activo:
        w.fallos_seguidos = 0
    await session.commit()
    integraciones.invalidar_cache(w.tenant_id)
    return _out(w)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar(webhook_id: int, session: AsyncSession = Depends(get_session)):
    w = await _webhook(session, webhook_id)
    tenant_id = w.tenant_id
    await session.delete(w)
    await session.commit()
    integraciones.invalidar_cache(tenant_id)


@router.post("/webhooks/{webhook_id}/rotar-secreto")
async def rotar(webhook_id: int, session: AsyncSession = Depends(get_session)):
    """El secreto viejo deja de valer en el acto: las entregas pendientes
    salen firmadas con el nuevo."""
    w = await _webhook(session, webhook_id)
    w.secreto = integraciones.nuevo_secreto()
    secreto = w.secreto
    await session.commit()
    return {"secreto": secreto}


@router.post("/webhooks/{webhook_id}/probar")
async def probar(webhook_id: int, session: AsyncSession = Depends(get_session)):
    """Manda un evento `ping` ya y devuelve cómo le fue."""
    w = await _webhook(session, webhook_id)
    if not w.activo:
        raise HTTPException(status_code=409, detail="El webhook está desactivado")
    e = EntregaWebhook(tenant_id=w.tenant_id, webhook_id=w.id, evento=integraciones.EVENTO_PRUEBA, estado="pendiente",
                       proximo_intento_at=datetime.utcnow(),
                       payload=integraciones._json({"evento": "ping", "empresa_id": w.tenant_id,
                                                    "creado": datetime.utcnow().isoformat() + "Z", "datos": {"mensaje": "Prueba desde NSPBX"}}))
    session.add(e)
    await session.commit()
    entrega_id, tenant_id = e.id, w.tenant_id
    await integraciones.entregar(tenant_id, entrega_id, forzar=True)
    session.expire_all()
    return _entrega_out(await session.get(EntregaWebhook, entrega_id))


@router.get("/webhooks/{webhook_id}/entregas")
async def entregas(
    webhook_id: int,
    estado: str | None = Query(default=None, pattern="^(pendiente|ok|fallida)$"),
    limite: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    await _webhook(session, webhook_id)
    q = select(EntregaWebhook).where(EntregaWebhook.webhook_id == webhook_id)
    if estado:
        q = q.where(EntregaWebhook.estado == estado)
    filas = (await session.execute(q.order_by(EntregaWebhook.id.desc()).limit(limite))).scalars().all()
    return [_entrega_out(e) for e in filas]


@router.post("/entregas/{entrega_id}/reintentar")
async def reintentar(entrega_id: int, session: AsyncSession = Depends(get_session)):
    e = await traer_propio(session, EntregaWebhook, entrega_id)
    if e is None:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    if e.estado == "ok":
        raise HTTPException(status_code=409, detail="Esa entrega ya llegó")
    # Vuelve a la cola con intentos nuevos; el repartidor la toma en segundos.
    e.estado, e.intentos, e.proximo_intento_at = "pendiente", 0, datetime.utcnow()
    await session.commit()
    return _entrega_out(e)
