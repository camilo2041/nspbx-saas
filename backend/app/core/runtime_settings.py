from dataclasses import dataclass

from app.core.config import settings as env_settings


@dataclass
class RuntimeSettings:
    """Configuración de INFRAESTRUCTURA, editable en caliente.

    Es un objeto por proceso, y con varias empresas eso solo sigue siendo
    correcto para lo que de verdad es único en la instalación. Acá quedó
    lo que cumple esa condición: hay UN FreeSWITCH para toda la
    plataforma —las empresas se separan por dominio SIP y por contexto de
    dialplan dentro de él, no levantando un motor por cliente—, así que
    la conexión al Event Socket es la misma para todas.

    Lo que salió de acá, y por qué:

    - `fs_domain` pasó a `Tenant.sip_domain`. Cambia por empresa, y
      además es el identificador con el que FreeSWITCH resuelve a quién
      pertenece cada teléfono. Tenerlo duplicado acá y en la tabla
      abriría la puerta a que difieran, y el síntoma sería que los
      teléfonos de una empresa dejan de encontrar su directorio.

    - `app_name` pasó a `SystemSettings`, que ahora tiene una fila por
      empresa: es el nombre que ve cada cliente en su panel.
    """

    fs_esl_host: str = env_settings.fs_esl_host
    fs_esl_port: int = env_settings.fs_esl_port
    fs_esl_password: str = env_settings.fs_esl_password
    fs_http_base: str = env_settings.fs_http_base


runtime_settings = RuntimeSettings()
