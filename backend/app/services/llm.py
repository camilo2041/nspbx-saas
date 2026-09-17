"""Cliente para el "cerebro" del voizbot conversacional — chat completions
+ tool/function calling, con la API compatible con OpenAI que hoy exponen
prácticamente todos los proveedores de LLM (DeepSeek, OpenAI, Groq,
Together AI, un servidor propio con vLLM/Ollama...). No está atado a
ninguno: `base_url`, `model` y la API key salen de Ajustes, así que sumar
un proveedor nuevo es cambiar tres campos ahí, no tocar este archivo."""

import json

import httpx

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": "Consulta los horarios libres para una fecha dada.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"}},
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_cita",
            "description": "Agenda una cita nueva una vez el paciente confirmó fecha y hora.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM, 24h"},
                },
                "required": ["patient_name", "date", "time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirmar_cita",
            "description": (
                "Deja registrado que el paciente confirmó que SÍ va a asistir a su próxima cita. "
                "Usala apenas lo diga; no hace falta pedirle más datos."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_cita",
            "description": "Cancela la próxima cita confirmada del paciente que llama.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reagendar_cita",
            "description": "Mueve la próxima cita del paciente a una nueva fecha/hora, una vez confirmada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "new_time": {"type": "string", "description": "HH:MM, 24h"},
                },
                "required": ["new_date", "new_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_promesa",
            "description": (
                "Registra la promesa de pago que la persona acaba de aceptar en una "
                "llamada de cobranza: cuánto se compromete a pagar, para qué fecha, "
                "y si es el pago total, un abono o un plan de cuotas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "monto": {"type": "number", "description": "Monto en pesos que la persona se compromete a pagar."},
                    "fecha": {"type": "string", "description": "Fecha prometida de pago en formato YYYY-MM-DD."},
                    "tipo": {
                        "type": "string",
                        "enum": ["completo", "abono", "cuotas"],
                        "description": "completo = paga toda la deuda; abono = paga una parte; cuotas = plan de pagos en varias cuotas.",
                    },
                    "cuotas": {"type": "integer", "description": "Número de cuotas, solo si tipo es 'cuotas'."},
                    "cliente": {"type": "string", "description": "Nombre de la persona que aceptó la promesa."},
                    "nota": {"type": "string", "description": "Detalle breve de lo acordado, ej. 'abono inicial de 50 mil y el resto en dos semanas'."},
                },
                "required": ["monto", "fecha", "tipo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminar_llamada",
            "description": "Cierra la conversación cuando ya no hay nada más que hacer (el paciente se despide, o ya se resolvió su solicitud).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def tools_para(nombres: tuple[str, ...] | None) -> list[dict]:
    """Subconjunto de herramientas para una gestión concreta.

    Exponerle al modelo solo lo que esa llamada necesita es una barrera
    real: si la persona marcó "reagendar", `agendar_cita` ni siquiera
    existe para el modelo, así que no puede crearle una cita nueva por
    equivocación en vez de mover la que ya tiene."""
    if not nombres:
        return TOOLS
    return [t for t in TOOLS if t["function"]["name"] in nombres]


async def chat(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict],
    tool_choice: str = "auto",
    tools: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Una vuelta de chat completion. Devuelve (mensaje, uso).

    El mensaje del asistente puede traer tool_calls. `uso` son los tokens
    que reporta el propio proveedor (`prompt_tokens`/`completion_tokens`),
    que es la única cifra fiable para medir el gasto — contar palabras del
    lado nuestro daría otro número.

    `tool_choice="none"` obliga al modelo a contestar con texto en vez de
    pedir otra herramienta — se usa para garantizar que el bot siempre
    tenga algo que decir al final del turno (ver `_llm_turn`)."""
    if not api_key:
        raise ValueError("Falta configurar la API key del modelo de lenguaje en Ajustes")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "tools": tools if tools is not None else TOOLS,
                "tool_choice": tool_choice,
                "temperature": 0.1,
            },
        )
    if resp.status_code == 401:
        raise ValueError("API key del modelo de lenguaje inválida")
    if resp.status_code >= 400:
        raise ValueError(f"El modelo de lenguaje rechazó la solicitud ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"], (data.get("usage") or {})


def parse_tool_calls(message: dict) -> list[tuple[str, dict, str]]:
    """[(tool_call_id, name, args_dict), ...] a partir del mensaje del asistente."""
    out = []
    for call in message.get("tool_calls") or []:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"]["arguments"] or "{}")
        except (ValueError, TypeError):
            args = {}
        out.append((call["id"], name, args))
    return out
