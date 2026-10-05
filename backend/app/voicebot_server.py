"""Punto de entrada del contenedor `voicebot`: el pipeline de IA en vivo
(control de llamada por ESL outbound socket + streaming de audio),
separado del backend de la API REST para que actualizar uno no corte
llamadas en curso del otro.

Antes, todo vivía en el mismo proceso (`app.main`): cada
`docker compose up --force-recreate backend` —algo que en una sesión
normal de trabajo pasa decenas de veces, cada vez que se toca cualquier
endpoint— tumbaba de golpe el socket ESL (puerto 8085) y el websocket de
audio de cualquier llamada de IA que estuviera en curso justo en ese
instante, sin ninguna forma de recuperarla: quien estuviera hablando con
el voizbot se quedaba con la llamada muerta a mitad de frase. Ahora un
cambio en la API REST —la inmensa mayoría de los despliegues— no toca
este proceso para nada.

Comparte el mismo código e imagen que el backend (mismo Dockerfile,
mismos módulos en app/services/*): lo único que cambia es QUÉ arranca en
cada contenedor. Ver docker-compose.yml, servicio `voicebot`, y
app/services/ai_agent.py para el pipeline en sí.

Sin migraciones de base acá a propósito: las corre el backend (app.main)
al arrancar, contra la misma Postgres. Duplicarlas acá no rompería nada
(los ALTER son idempotentes) pero sería trabajo de más en cada arranque
por ninguna ganancia.
"""

import logging

# Ver la misma línea en app/main.py: sin esto, los logger.info() de todo
# el pipeline de IA (incluido "arrancó", y cualquier traza por llamada)
# se pierden en silencio — uvicorn no configura el logger raíz.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI

from app.core.auditoria import instalar_filtro_de_secretos
from app.core.config import settings
from app.core.database import engine
from app.services import ai_agent, ambience

logger = logging.getLogger(__name__)
instalar_filtro_de_secretos()


async def lifespan(app: FastAPI):
    # Se sintetiza al arrancar y no en la primera llamada: generarlo
    # cuesta un par de segundos y no puede pagarlos un paciente en línea.
    ambience.ensure_typing_loop()
    esl_server = await ai_agent.start_server()
    logger.info("voicebot: listo (ESL outbound socket :8085 + /ws/voicebot)")
    yield
    esl_server.close()
    await engine.dispose()


app = FastAPI(title=f"{settings.app_name} — voicebot", lifespan=lifespan)

# Sin guardia de sesión: lo usa FreeSWITCH (mod_audio_fork), no una
# persona con navegador. Este servicio ni siquiera se publica al host
# (ver docker-compose.yml) — solo es alcanzable desde la red interna de
# Docker, donde vive FreeSWITCH.
app.include_router(ai_agent.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voicebot"}
