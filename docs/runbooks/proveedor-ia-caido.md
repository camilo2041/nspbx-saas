# Runbook 6 — Proveedor de IA caído

El voizbot depende de tres servicios externos que se eligen por separado en
Ajustes: el **modelo de lenguaje** (DeepSeek, OpenAI, Groq…), la **voz**
(edge-tts, Deepgram Aura, ElevenLabs) y la **transcripción** (Deepgram,
ElevenLabs Scribe). Si uno cae, el voizbot no entiende, no responde o no
habla. La telefonía (extensiones, colas, troncales) sigue funcionando.

Severidad: **S2** (varias empresas sin voizbot) o **S3** (una empresa con
su clave vencida o sin saldo).

## Síntomas

- Llamadas al voizbot que quedan en silencio o se cortan al poco.
- Consumo de IA: conversaciones con resultado «Error» o «Sin respuesta»
  que suben de golpe.
- Log del voicebot:
  ```bash
  docker compose logs --tail=200 voicebot | grep -iE "error|rechaz|inválida|timeout"
  ```
  - «API key del modelo de lenguaje inválida» / «rechazó la solicitud (401/402/429)»:
    clave vencida, sin saldo o límite de uso → es de **una** empresa.
  - Timeouts o 5xx en todas las empresas → el proveedor está caído.

## Confirmar

1. Página de estado del proveedor (status.openai.com, status.deepseek.com,
   status.elevenlabs.io, status.deepgram.com).
2. Probar el bot sin llamar: Menú → Voizbots → el bot → conversar (usa el
   mismo modelo de la empresa). Si responde, el modelo funciona y el
   problema está en voz o transcripción.
3. Saldo y límites en el panel del proveedor.

## Contener

Las tres piezas se cambian en Ajustes de la empresa y aplican a la
siguiente llamada, sin reiniciar nada:

- **Modelo caído**: Ajustes → Modelo de lenguaje → otro proveedor (atajo
  DeepSeek / OpenAI / Groq / Together) y su API key. Conviene tener una
  clave de respaldo de un segundo proveedor creada de antemano.
- **Voz caída**: Ajustes → Voz y transcripción → «Gratis (edge-tts)», que
  no necesita clave y tiene voces de Colombia.
- **Transcripción caída**: cambiar entre Deepgram y ElevenLabs Scribe
  (necesita la clave del otro).
- **Sin alternativa a mano**: sacar las llamadas del voizbot para que las
  atienda gente. Rutas entrantes → la ruta que va al voizbot → destino una
  cola o una extensión. Y detener las campañas del voizbot (Campañas →
  Detener): esperan sin dar números por fallidos.

## Recuperar

- Volver al proveedor original cuando su página de estado lo confirme, con
  una llamada de prueba.
- Reiniciar campañas detenidas y devolver la ruta entrante al voizbot.
- Revisar en Consumo de IA que las conversaciones vuelven a «Completada».

## Cerrar

Informe: proveedor, duración, llamadas afectadas (Consumo de IA, rango del
incidente). Si una empresa no tenía clave de respaldo para el modelo,
dejarla configurada.
