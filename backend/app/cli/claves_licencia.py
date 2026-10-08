"""Genera el par de claves Ed25519 de las licencias (docs/plan-fase-k.md).

    docker compose exec backend python -m app.cli.claves_licencia

- LICENCIA_CLAVE_PRIVADA va SOLO en el .env de la central. Quien la tenga
  puede fabricar licencias: guárdala también fuera del servidor.
- LICENCIA_CLAVE_PUBLICA va en las imágenes que se instalan en los clientes
  (secreto del repositorio para el workflow de publicación).

Con una privada ya puesta, muestra su pública en vez de generar otra:
cambiar el par deja sin licencia a todas las instalaciones existentes.
"""

from app.core.config import settings
from app.services import licencia_firmada as lf


def main() -> None:
    if settings.licencia_clave_privada:
        print("Esta central ya tiene LICENCIA_CLAVE_PRIVADA. Su clave pública es:\n")
        print(f"LICENCIA_CLAVE_PUBLICA={lf.publica_de(settings.licencia_clave_privada)}")
        return
    privada, publica = lf.generar_par()
    print("Par nuevo. La privada va SOLO en el .env de la central:\n")
    print(f"LICENCIA_CLAVE_PRIVADA={privada}\n")
    print("La pública, en las imágenes de las instalaciones locales:\n")
    print(f"LICENCIA_CLAVE_PUBLICA={publica}")


if __name__ == "__main__":
    main()
