"""Qué números marca una campaña ahora, y cuándo vuelve a marcar uno.

Un número se puede marcar si está pendiente, ya pasó su `proximo_intento_at`
(reciclaje), su lista está activa y no está en la lista de no llamar. El
orden: prioridad de la lista, prioridad del número y antigüedad.

`tomar` usa FOR UPDATE SKIP LOCKED: si algún día hay dos marcadores, no
toman el mismo número. Corre en la sesión de la empresa de la campaña
(workers/dialer.py), así que RLS y el filtro de la aplicación aplican.

Un número que está en no llamar pasa a `no_llamar` (final): quedarse en
pendiente haría que la campaña no terminara nunca.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from app.models import Campaign, CampaignNumber, Lista, NoLlamar
from app.services import crm

# Resultados del intento anterior que admiten una espera antes del siguiente.
RESULTADOS_RECICLABLES = ("busy", "noanswer", "failed")
MAX_MINUTOS_RECICLAJE = 7 * 24 * 60
_VUELTAS = 5


def condiciones_disponibles(campaign_id: int, ahora: datetime):
    return (
        CampaignNumber.campaign_id == campaign_id,
        CampaignNumber.status == "pending",
        or_(CampaignNumber.proximo_intento_at.is_(None), CampaignNumber.proximo_intento_at <= ahora),
        or_(CampaignNumber.lista_id.is_(None), Lista.activa.is_(True)),
    )


async def tomar(session, campaign: Campaign, cuantos: int, ahora: datetime | None = None) -> list[CampaignNumber]:
    """Hasta `cuantos` números listos para marcar, ya marcados como
    "dialing" (sin commit: lo hace quien llama)."""
    ahora = ahora or datetime.utcnow()
    tomados: list[CampaignNumber] = []
    for _ in range(_VUELTAS):
        falta = cuantos - len(tomados)
        if falta <= 0:
            break
        candidatos = list(
            (
                await session.execute(
                    select(CampaignNumber)
                    .outerjoin(Lista, Lista.id == CampaignNumber.lista_id)
                    .where(*condiciones_disponibles(campaign.id, ahora))
                    .order_by(
                        func.coalesce(Lista.prioridad, 0).desc(),
                        CampaignNumber.prioridad.desc(),
                        CampaignNumber.id,
                    )
                    .limit(falta)
                    .with_for_update(of=CampaignNumber, skip_locked=True)
                )
            ).scalars()
        )
        if not candidatos:
            break
        claves = {crm.clave_telefono(n.phone) for n in candidatos}
        bloqueadas = set(
            (
                await session.execute(
                    select(NoLlamar.telefono_clave).where(
                        NoLlamar.telefono_clave.in_(claves), crm.vigente_no_llamar(ahora)
                    )
                )
            ).scalars()
        )
        for n in candidatos:
            if crm.clave_telefono(n.phone) in bloqueadas:
                n.status = "no_llamar"
                n.last_error = "En la lista de no llamar"
            else:
                n.status = "dialing"
                n.attempts += 1
                n.ultimo_intento_at = ahora
                tomados.append(n)
    return tomados


def minutos_de_espera(campaign: Campaign | None, resultado: str) -> int:
    reglas = (campaign.reglas_reciclaje if campaign else None) or {}
    try:
        minutos = int(reglas.get(resultado) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(minutos, MAX_MINUTOS_RECICLAJE))


def reprogramar(numero: CampaignNumber, campaign: Campaign | None, resultado: str, ahora: datetime | None = None) -> None:
    """El número vuelve a pendiente; según la regla de la campaña, no antes
    de unos minutos."""
    ahora = ahora or datetime.utcnow()
    minutos = minutos_de_espera(campaign, resultado)
    numero.status = "pending"
    numero.proximo_intento_at = ahora + timedelta(minutes=minutos) if minutos else None


def validar_reglas(reglas: dict | None) -> dict | None:
    """Reglas de reciclaje limpias, o ValueError."""
    if not reglas:
        return None
    limpio = {}
    for resultado, minutos in reglas.items():
        if resultado not in RESULTADOS_RECICLABLES:
            raise ValueError(f"«{resultado}» no es un resultado reciclable ({', '.join(RESULTADOS_RECICLABLES)})")
        if isinstance(minutos, bool) or not isinstance(minutos, int) or not 0 <= minutos <= MAX_MINUTOS_RECICLAJE:
            raise ValueError(f"los minutos de «{resultado}» van de 0 a {MAX_MINUTOS_RECICLAJE}")
        if minutos:
            limpio[resultado] = minutos
    return limpio or None


async def reiniciar_campana(session, campaign_id: int) -> int:
    """«Reintentar»: los números terminados vuelven a pendiente, sin espera.
    Los de no llamar no: siguen en la lista."""
    resultado = await session.execute(
        update(CampaignNumber)
        .where(
            CampaignNumber.campaign_id == campaign_id,
            CampaignNumber.status.in_(["failed", "done", "busy", "noanswer"]),
        )
        .values(status="pending", attempts=0, last_error=None, proximo_intento_at=None)
    )
    return resultado.rowcount
