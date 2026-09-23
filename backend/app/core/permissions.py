"""Qué puede hacer cada rol.

Los endpoints piden un PERMISO, no un rol. La diferencia importa: cuando
mañana haya que crear un rol nuevo (auditor, jefe de agenda), se agrega
una fila a `PERMISOS_POR_ROL` y listo; si los endpoints preguntaran
`if rol == "admin"`, habría que revisarlos uno por uno y siempre se
escapa alguno.

Regla de oro de la tabla: `admin` tiene todo. Ese es el único rol que
puede tocar credenciales, troncales y usuarios.
"""

# --- Roles -----------------------------------------------------------

ADMIN = "admin"
SUPERVISOR = "supervisor"
COORDINADOR = "coordinador"
ASESOR = "asesor"
# Usuario de la PLATAFORMA (tenant_id NULL): el que da de alta empresas y
# puede entrar a cualquiera. Es el único rol por encima del admin de una
# empresa. Ver docs/arquitectura-multitenant.md.
PLATAFORMA = "plataforma"

ROLES = (ADMIN, SUPERVISOR, COORDINADOR, ASESOR, PLATAFORMA)

ETIQUETAS = {
    ADMIN: "Administrador",
    SUPERVISOR: "Supervisor",
    COORDINADOR: "Coordinador",
    ASESOR: "Asesor",
    PLATAFORMA: "Plataforma",
}

DESCRIPCIONES = {
    ADMIN: "Control total: usuarios, ajustes, troncales y toda la operación.",
    SUPERVISOR: "Supervisa la operación completa: llamadas, colas, campañas, "
    "voizbots y consumo de IA. No toca la configuración del sistema.",
    COORDINADOR: "Coordina el día a día: agenda, campañas y llamadas. "
    "Sin acceso a la infraestructura telefónica.",
    ASESOR: "Trabaja sobre su extensión: softphone, sus propias llamadas y la agenda.",
    PLATAFORMA: "Opera la plataforma: crea y administra las empresas.",
}

# El asesor es el único rol que exige una extensión: sin ella no puede
# atender, y su historial de llamadas se filtra por ese número.
REQUIERE_EXTENSION = (ASESOR,)


# --- Permisos --------------------------------------------------------

USUARIOS_GESTIONAR = "usuarios:gestionar"
AJUSTES_GESTIONAR = "ajustes:gestionar"
# Crear/editar/eliminar EMPRESAS (tenants). Es solo del rol de plataforma:
# un admin de empresa gestiona su central, no las demás.
EMPRESAS_GESTIONAR = "empresas:gestionar"
# Troncales, extensiones y rutas entrantes. Es solo de admin y no hay un
# "telefonia:ver" aparte a propósito: esas respuestas incluyen las
# credenciales SIP (contraseña de extensión, usuario y clave de la
# troncal), así que "mirar" ya es tener las llaves de la central. Quien
# necesita marcar usa su propia extensión vía /api/auth/mi-entorno.
TELEFONIA_GESTIONAR = "telefonia:gestionar"
COLAS_GESTIONAR = "colas:gestionar"
CAMPANAS_GESTIONAR = "campanas:gestionar"
VOIZBOTS_GESTIONAR = "voizbots:gestionar"
VOIZBOTS_VER = "voizbots:ver"
LLAMADAS_VER_TODAS = "llamadas:ver_todas"
LLAMADAS_VER_PROPIAS = "llamadas:ver_propias"
CITAS_GESTIONAR = "citas:gestionar"
CONSUMO_IA_VER = "consumo_ia:ver"
SOFTPHONE_USAR = "softphone:usar"

PERMISOS_POR_ROL: dict[str, frozenset[str]] = {
    ADMIN: frozenset(
        {
            USUARIOS_GESTIONAR,
            AJUSTES_GESTIONAR,
            TELEFONIA_GESTIONAR,
            COLAS_GESTIONAR,
            CAMPANAS_GESTIONAR,
            VOIZBOTS_GESTIONAR,
            VOIZBOTS_VER,
            LLAMADAS_VER_TODAS,
            LLAMADAS_VER_PROPIAS,
            CITAS_GESTIONAR,
            CONSUMO_IA_VER,
            SOFTPHONE_USAR,
        }
    ),
    SUPERVISOR: frozenset(
        {
            COLAS_GESTIONAR,
            CAMPANAS_GESTIONAR,
            VOIZBOTS_GESTIONAR,
            VOIZBOTS_VER,
            LLAMADAS_VER_TODAS,
            LLAMADAS_VER_PROPIAS,
            CITAS_GESTIONAR,
            CONSUMO_IA_VER,
            SOFTPHONE_USAR,
        }
    ),
    COORDINADOR: frozenset(
        {
            CAMPANAS_GESTIONAR,
            VOIZBOTS_VER,
            LLAMADAS_VER_TODAS,
            LLAMADAS_VER_PROPIAS,
            CITAS_GESTIONAR,
            CONSUMO_IA_VER,
        }
    ),
    ASESOR: frozenset(
        {
            LLAMADAS_VER_PROPIAS,
            CITAS_GESTIONAR,
            SOFTPHONE_USAR,
        }
    ),
    # El rol de plataforma solo administra empresas. No ve datos de
    # operación de ninguna empresa (para eso entra a cada una con su
    # propio usuario): sus rutas usan la sesión del dueño, no RLS.
    PLATAFORMA: frozenset(
        {
            EMPRESAS_GESTIONAR,
        }
    ),
}


# --- Personalización por empresa -------------------------------------
# La tabla `role_permissions` guarda solo las DIFERENCIAS respecto de la
# matriz de arriba (ver el modelo). Se cachean en el proceso porque los
# permisos se evalúan en CADA petición: ir a la base en cada `requiere()`
# multiplicaría las consultas por el número de endpoints protegidos.
#
# El caché se rellena al arrancar y se invalida al guardar. Asume UN
# proceso de aplicación, que es como corre hoy (ver docker-compose); con
# varios workers habría que mover la invalidación a Postgres (LISTEN/NOTIFY).
_OVERRIDES: dict[tuple[int, str], dict[str, bool]] = {}

# Permisos que una empresa NO puede tocar, pase lo que pase en la tabla.
#
# EMPRESAS_GESTIONAR es la frontera con la plataforma: quien lo tiene crea
# y edita empresas, incluidos sus packs contratados. Si una empresa
# pudiera otorgárselo, se habilitaría módulos que no pagó.
_NUNCA_OTORGABLES = frozenset({EMPRESAS_GESTIONAR})

# Sin estos dos, un admin que se equivoca de casilla deja a su empresa sin
# NADIE que pueda revertirlo: no habría quien administre usuarios ni quien
# entre a la pantalla de permisos. La única salida sería editar la base a
# mano. Se ignoran los intentos de quitarlos en vez de fallar, para que la
# interfaz no tenga que conocer esta regla.
_IRRENUNCIABLES_ADMIN = frozenset({USUARIOS_GESTIONAR, AJUSTES_GESTIONAR})


def cargar_overrides(filas) -> None:
    """Rellena el caché desde las filas de `role_permissions`."""
    nuevo: dict[tuple[int, str], dict[str, bool]] = {}
    for f in filas:
        nuevo.setdefault((f.tenant_id, f.role), {})[f.permission] = bool(f.allowed)
    _OVERRIDES.clear()
    _OVERRIDES.update(nuevo)


def permisos_de(rol: str, tenant_id: int | None = None) -> frozenset[str]:
    """Permisos efectivos del rol, ya con la personalización de la empresa."""
    base = PERMISOS_POR_ROL.get(rol, frozenset())
    # El rol de plataforma no se personaliza: no pertenece a ninguna
    # empresa, así que no hay quién pudiera hacerlo sin pisar la frontera.
    if tenant_id is None or rol == PLATAFORMA:
        return base
    cambios = _OVERRIDES.get((tenant_id, rol))
    if not cambios:
        return base
    efectivos = set(base)
    for permiso, permitido in cambios.items():
        if permitido:
            efectivos.add(permiso)
        else:
            efectivos.discard(permiso)
    efectivos -= _NUNCA_OTORGABLES
    if rol == ADMIN:
        efectivos |= _IRRENUNCIABLES_ADMIN
    return frozenset(efectivos)


def puede(rol: str, permiso: str, tenant_id: int | None = None) -> bool:
    return permiso in permisos_de(rol, tenant_id)


def personalizable(rol: str) -> bool:
    """¿Esta empresa puede editar los permisos de este rol?"""
    return rol in ROLES and rol != PLATAFORMA


def editable(rol: str, permiso: str) -> bool:
    """¿Esta casilla concreta se puede cambiar, o está fija por diseño?"""
    if permiso in _NUNCA_OTORGABLES:
        return False
    if rol == ADMIN and permiso in _IRRENUNCIABLES_ADMIN:
        return False
    return True


# Catálogo para la interfaz: qué permisos existen y cómo se llaman en
# castellano. Vive acá y no en el frontend para que agregar un permiso sea
# tocar un solo archivo.
ETIQUETAS_PERMISOS = {
    USUARIOS_GESTIONAR: "Gestionar usuarios",
    AJUSTES_GESTIONAR: "Gestionar ajustes del sistema",
    EMPRESAS_GESTIONAR: "Gestionar empresas",
    TELEFONIA_GESTIONAR: "Telefonía: troncales, extensiones y rutas",
    COLAS_GESTIONAR: "Gestionar colas",
    CAMPANAS_GESTIONAR: "Gestionar campañas y cobranza",
    VOIZBOTS_GESTIONAR: "Editar voizbots",
    VOIZBOTS_VER: "Ver voizbots",
    LLAMADAS_VER_TODAS: "Ver todas las llamadas",
    LLAMADAS_VER_PROPIAS: "Ver las llamadas propias",
    CITAS_GESTIONAR: "Gestionar citas",
    CONSUMO_IA_VER: "Ver consumo de IA",
    SOFTPHONE_USAR: "Usar el softphone",
}

TODOS_LOS_PERMISOS = tuple(ETIQUETAS_PERMISOS)
