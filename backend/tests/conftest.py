"""Base común de las pruebas: Postgres real, RLS activo y dos empresas espejo.

Las pruebas de aislamiento no sirven contra SQLite ni con mocks: lo que se
prueba es justamente lo que hace Postgres (Row-Level Security, el rol sin
BYPASSRLS, `set_config` por transacción). Por eso necesitan un servidor de
verdad. La base se borra y se vuelve a migrar al empezar, con la misma
función `migrar()` que usa el arranque de producción.

Variables (todas opcionales; los valores por omisión sirven para el
Postgres del workflow de CI):

    TEST_DATABASE_URL       conexión del DUEÑO (superusuario) a una base
                            DESCARTABLE — se borra entera.
    TEST_DATABASE_URL_APP   conexión del rol restringido (se crea solo).

Las dos empresas tienen EXACTAMENTE los mismos recursos —misma extensión
1000, misma troncal, mismo nombre de campaña— porque ahí es donde un
aislamiento mal hecho se confunde. Lo único que cambia es una marca en los
textos ("alfa" / "zzbeta") y los teléfonos, para poder buscar en cualquier
respuesta si se coló algo de la otra.
"""

import os
import tempfile
from urllib.parse import urlsplit

# --- Entorno ANTES de importar la aplicación ------------------------------
# app.core.config lee el entorno al importarse, y los motores de la base se
# crean en ese mismo momento.
_DUENO = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/nspbx_test"
)
_partes = urlsplit(_DUENO)
_APP = os.environ.get(
    "TEST_DATABASE_URL_APP",
    _partes._replace(netloc="nspbx_app:nspbx_app_test@" + _partes.netloc.split("@")[-1]).geturl(),
)
_TMP = tempfile.mkdtemp(prefix="nspbx-tests-")
for _sub in ("conf/sip_profiles/external", "sounds", "recordings", "backups"):
    os.makedirs(os.path.join(_TMP, _sub), exist_ok=True)

os.environ.update(
    {
        "DATABASE_URL": _DUENO,
        "DATABASE_URL_APP": _APP,
        "AUTH_SECRET": "x" * 48,
        "DATA_ENCRYPTION_KEY": "Y2xhdmUtZGUtcHJ1ZWJhLWRlLTMyLWJ5dGVzLW9rISE=",  # gitleaks:allow (clave de prueba)
        "FS_XML_SECRET": "secreto-de-prueba-fs",
        "ENTORNO": "desarrollo",
        # Puerto cerrado: si un endpoint intenta hablar con FreeSWITCH,
        # falla al instante en vez de colgar la prueba.
        "FS_ESL_HOST": "127.0.0.1",
        "FS_ESL_PORT": "9",
        "FS_HTTP_BASE": "http://127.0.0.1:9",
        "FS_CONF_DIR": os.path.join(_TMP, "conf"),
        "FS_SOUNDS_DIR": os.path.join(_TMP, "sounds"),
        "RECORDINGS_DIR": os.path.join(_TMP, "recordings"),
        "BACKUPS_DIR": os.path.join(_TMP, "backups"),
        "PROXIES_CONFIABLES": "0",
        # Las pruebas generales crean administradores con crear_token, sin
        # pasar por el login: si MFA fuera obligatorio, todos quedarían
        # limitados a activarlo. test_mfa.py lo vuelve obligatorio.
        "MFA_OBLIGATORIO": "",
    }
)

from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api import role_permissions  # noqa: E402
from app.core import permissions  # noqa: E402
from app.core.database import async_session, engine  # noqa: E402
from app.core.security import crear_token, hash_password  # noqa: E402
from app.main import _TABLAS_CON_RLS, app, migrar  # noqa: E402
from app.models import (  # noqa: E402
    AiCallUsage,
    Appointment,
    CallLog,
    Campaign,
    CampaignNumber,
    Debt,
    Extension,
    InboundRoute,
    License,
    OutboundRoute,
    PaymentPromise,
    Queue,
    Tenant,
    Trunk,
    User,
    VoiceBot,
    VoiceBotVersion,
)
from app.services.ajustes import get_or_create_settings  # noqa: E402

FS_SECRET = os.environ["FS_XML_SECRET"]


@dataclass
class Empresa:
    """Una empresa sembrada y los ids de cada uno de sus recursos."""

    id: int
    slug: str
    dominio: str
    marca: str  # texto que solo aparece en los datos de esta empresa
    telefono: str  # prefijo de teléfono que solo usa esta empresa
    ids: dict[str, int] = field(default_factory=dict)
    usuarios: dict[str, int] = field(default_factory=dict)

    def token(self, rol: str = permissions.ADMIN) -> str:
        return crear_token(self.usuarios[rol], rol, self.id)[0]

    def cabeceras(self, rol: str = permissions.ADMIN) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(rol)}"}


async def _reiniciar_base() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


async def _sembrar(session, slug: str, marca: str, telefono: str) -> Empresa:
    t = Tenant(
        name=f"Empresa {marca}",
        slug=slug,
        sip_domain=f"{slug}.pbx.test",
        subdomain=slug,
        modules="voicebot,pbx",
        enabled=True,
    )
    session.add(t)
    await session.flush()
    e = Empresa(id=t.id, slug=slug, dominio=t.sip_domain, marca=marca, telefono=telefono)
    tid = t.id

    session.add(
        License(
            tenant_id=tid,
            plan="enterprise",
            status="active",
            started_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=365),
        )
    )
    await session.flush()
    await get_or_create_settings(session, tid)

    trunk = Trunk(
        tenant_id=tid,
        name="principal",
        gateway_host=f"sip.{marca}.carrier.test",
        username=f"usuario-{marca}",
        password=f"clave-troncal-{marca}",
        register_enabled=False,
    )
    ext = Extension(tenant_id=tid, number="1000", password=f"clave-sip-{marca}", caller_id_name=f"Recepcion {marca}")
    bot = VoiceBot(tenant_id=tid, name=f"bot-{marca}", bot_type="ivr", welcome_message=f"Hola {marca}")
    queue = Queue(tenant_id=tid, name="soporte", extension="5000", agents='["1000"]')
    session.add_all([trunk, ext, bot, queue])
    await session.flush()

    camp = Campaign(tenant_id=tid, name="cobro-octubre", trunk_id=trunk.id, voicebot_id=bot.id, message_template=f"Hola {marca}")
    session.add(camp)
    await session.flush()
    numero = CampaignNumber(tenant_id=tid, campaign_id=camp.id, phone=f"{telefono}01")
    entrante = InboundRoute(
        tenant_id=tid, name=f"entrada-{marca}", did_pattern=f"{telefono}00",
        destination_type="extension", destination_value="1000",
    )
    saliente = OutboundRoute(tenant_id=tid, name=f"salida-{marca}", pattern="3XXXXXXXXX", trunk_ids=str(trunk.id))
    llamada = CallLog(
        tenant_id=tid, extension_id=ext.id, uuid=f"uuid-{marca}", caller_number="1000",
        callee_number=f"{telefono}02", direction="outbound", status="answered",
        recording_path=f"/var/lib/freeswitch/recordings/{marca}.wav",
        summary=f"Resumen privado de {marca}", started_at=datetime.utcnow(),
    )
    cita = Appointment(
        tenant_id=tid, patient_name=f"Paciente {marca}", phone=f"{telefono}03",
        appointment_date=datetime.utcnow() + timedelta(days=3), notes=f"Nota clinica {marca}",
    )
    deuda = Debt(tenant_id=tid, phone=f"{telefono}04", debtor_name=f"Deudor {marca}", amount=1000, notes=f"Deuda {marca}")
    session.add_all([numero, entrante, saliente, llamada, cita, deuda])
    await session.flush()
    promesa = PaymentPromise(
        tenant_id=tid, debt_id=deuda.id, phone=f"{telefono}04", debtor_name=f"Deudor {marca}",
        amount_promised=500, promise_date=datetime.utcnow() + timedelta(days=5),
    )
    uso = AiCallUsage(tenant_id=tid, call_uuid=f"ia-{marca}", phone=f"{telefono}05", action_patient_name=f"Paciente {marca}")
    version = VoiceBotVersion(
        tenant_id=tid, voicebot_id=bot.id, version=1, name=bot.name, bot_type="ivr",
        welcome_message=f"Hola {marca}", reason="semilla",
    )
    session.add_all([promesa, uso, version])
    await session.flush()

    for rol in (permissions.ADMIN, permissions.SUPERVISOR, permissions.ASESOR):
        u = User(
            tenant_id=tid,
            username=f"{rol}-{slug}",
            full_name=f"{rol} {marca}",
            email=f"{rol}@{marca}.test",
            password_hash=hash_password("clave-de-prueba"),
            role=rol,
            extension_id=ext.id if rol == permissions.ASESOR else None,
            enabled=True,
        )
        session.add(u)
        await session.flush()
        e.usuarios[rol] = u.id

    e.ids = {
        "trunk": trunk.id,
        "extension": ext.id,
        "voicebot": bot.id,
        "queue": queue.id,
        "campaign": camp.id,
        "campaign_number": numero.id,
        "inbound_route": entrante.id,
        "outbound_route": saliente.id,
        "call": llamada.id,
        "appointment": cita.id,
        "debt": deuda.id,
        "promise": promesa.id,
        "user": e.usuarios[permissions.SUPERVISOR],
        "voicebot_version": version.id,
    }
    return e


@dataclass
class Mundo:
    alfa: Empresa
    beta: Empresa
    plataforma_id: int

    def cabeceras_plataforma(self) -> dict[str, str]:
        token = crear_token(self.plataforma_id, permissions.PLATAFORMA, None)[0]
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
async def mundo() -> Mundo:
    await _reiniciar_base()
    await migrar()
    async with async_session() as session:
        alfa = await _sembrar(session, "alfa", "alfa", "5730011111")
        beta = await _sembrar(session, "beta", "zzbeta", "5730099999")
        plataforma = User(
            tenant_id=None, username="plataforma", full_name="Plataforma",
            password_hash=hash_password("clave-de-prueba"), role=permissions.PLATAFORMA, enabled=True,
        )
        session.add(plataforma)
        await session.commit()
        await role_permissions.recargar_cache(session)
    return Mundo(alfa=alfa, beta=beta, plataforma_id=plataforma.id)


# Modo "solo la aplicación": la sesión de la API usa el rol DUEÑO, que se
# saltea RLS. Así se prueba que la segunda capa (el filtro por empresa en
# el código) aísla por sí sola, sin la red de seguridad de la base. Las
# pruebas que verifican RLS en sí no tienen sentido en este modo y se
# saltean (ver `requiere_rls`).
SIN_RLS = os.environ.get("NSPBX_TEST_SIN_RLS") == "1"
requiere_rls = pytest.mark.skipif(SIN_RLS, reason="prueba RLS en sí; en modo sin RLS no aplica")


@pytest.fixture(scope="session")
async def cliente(mundo) -> httpx.AsyncClient:
    if SIN_RLS:
        from app.core import database

        database.app_session.configure(bind=database.engine)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as c:
        yield c


async def foto_de_empresa(tenant_id: int) -> dict[str, list]:
    """Todas las filas de una empresa, leídas como dueño (sin RLS).

    Comparar la foto antes y después de un ataque es la prueba más
    directa de que no se escribió nada: no depende de qué código HTTP haya
    devuelto el endpoint."""
    foto: dict[str, list] = {}
    async with engine.connect() as conn:
        for tabla in _TABLAS_CON_RLS:
            filas = await conn.execute(
                text(f"SELECT * FROM {tabla} WHERE tenant_id = :t ORDER BY id"), {"t": tenant_id}
            )
            foto[tabla] = [tuple(f) for f in filas]
        filas = await conn.execute(text("SELECT * FROM tenants WHERE id = :t"), {"t": tenant_id})
        foto["tenants"] = [tuple(f) for f in filas]
    return foto
