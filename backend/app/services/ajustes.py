"""Ajustes del sistema POR EMPRESA, en un solo lugar.

Reemplaza a los ~16 `session.get(SystemSettings, 1)` que quedaron
repartidos por el código cuando el sistema asumía una sola empresa. Ahora
hay una fila por tenant y estos helpers son la forma única de pedirla:

- Con una sesión de la API (RLS) y sin `tenant_id`: la política de
  Row-Level Security ya deja ver únicamente la fila de la empresa atada a
  la sesión, así que un SELECT sin filtro devuelve exactamente esa.

- Con `tenant_id` explícito: para lo que corre SIN usuario detrás —los
  workers, el voizbot, los endpoints que consulta FreeSWITCH—, que usan la
  sesión del dueño (sin RLS) y no tienen un token del cual deducir la
  empresa. Pasarla a mano es lo que hace visible de qué empresa se habla.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as env_settings
from app.models import SystemSettings, Tenant


async def ajustes_de(session: AsyncSession, tenant_id: int | None = None) -> SystemSettings | None:
    consulta = select(SystemSettings)
    if tenant_id is not None:
        consulta = consulta.where(SystemSettings.tenant_id == tenant_id)
    return (await session.execute(consulta)).scalars().first()


# Nombre que toma el panel (Ajustes -> app_name) según el tipo de negocio
# de la empresa. Se siembra al crear la empresa; el admin puede cambiarlo.
_NOMBRE_POR_TIPO = {
    "clinica": "Consultorio",
    "cobranza": "Gestión de cartera",
    "general": env_settings.app_name,
}


async def get_or_create_settings(
    session: AsyncSession, tenant_id: int | None = None
) -> SystemSettings:
    row = await ajustes_de(session, tenant_id)
    if not row:
        # El dominio SIP se siembra desde la EMPRESA (Tenant.sip_domain) y
        # no desde un default estático: es la única forma de que el campo
        # "Dominio SIP" de Ajustes y el dominio con el que FreeSWITCH
        # identifica a la empresa nunca difieran de entrada.
        dominio = None
        nombre = None
        if tenant_id is not None:
            tenant = await session.get(Tenant, tenant_id)
            if tenant:
                dominio = tenant.sip_domain
                nombre = _NOMBRE_POR_TIPO.get(tenant.business_type)
        row = SystemSettings(
            tenant_id=tenant_id,
            app_name=nombre or env_settings.app_name,
            fs_domain=dominio or "nspbx.local",
            fs_esl_host=env_settings.fs_esl_host,
            fs_esl_port=env_settings.fs_esl_port,
            # Vacía a propósito: copiar la contraseña real a la fila de CADA empresa
            # la dejaba visible para todos sus administradores. La conexión usa la
            # del entorno (ver core/runtime_settings.py).
            fs_esl_password="",
            fs_http_base=env_settings.fs_http_base,
            sip_ws_url=env_settings.sip_ws_url,
            sip_server_ip=env_settings.sip_server_ip,
            sip_server_port=env_settings.sip_server_port,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def dominios_tenants(session: AsyncSession) -> dict[int, str]:
    """tenant_id -> sip_domain. Lo usa el generador de configuración de
    FreeSWITCH (colas de mod_callcenter, contextos) que necesita el dominio
    de cada empresa para nombrar las cosas sin pisarse entre tenants."""
    res = await session.execute(select(Tenant.id, Tenant.sip_domain))
    return {tid: d for tid, d in res.all()}
