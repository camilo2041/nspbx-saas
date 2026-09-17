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


def permisos_de(rol: str) -> frozenset[str]:
    return PERMISOS_POR_ROL.get(rol, frozenset())


def puede(rol: str, permiso: str) -> bool:
    return permiso in permisos_de(rol)
