"""Simulador del predictivo: agentes y clientes virtuales.

Antes de marcar a gente real (y para que CI lo compruebe en cada cambio),
el controlador del predictivo corre contra una operación simulada: agentes
con un tiempo de conversación aleatorio y clientes que contestan con cierta
probabilidad tras un timbre aleatorio. Usa EXACTAMENTE las funciones del
motor real (`a_lanzar`, `a_lanzar_predictivo`, `ajustar_factor`, `Ventana`): lo que se valida acá
es lo que corre en producción.

    python -m app.services.simulador_predictivo     # un informe rápido
"""

import random
from dataclasses import dataclass

from app.services import predictivo


@dataclass
class Parametros:
    agentes: int = 10
    contacto: float = 0.30  # probabilidad de que conteste una persona
    aht_s: float = 90.0  # conversación promedio
    acw_s: float = 10.0  # disposición después de colgar
    ring_min_s: float = 4.0
    ring_max_s: float = 20.0
    temporizador_s: float = 2.0
    objetivo_pct: float = 3.0
    nivel_inicial: float = 1.0
    nivel_max: float = 3.0
    duracion_s: int = 3 * 3600
    paso_s: float = 1.0
    semilla: int = 7


@dataclass
class Resultado:
    metodo: str
    intentos: int
    contestadas: int
    abandonadas: int
    conversaciones: int
    tiempo_hablado_s: float
    espera_agentes_s: float
    nivel_final: float
    factor_final: float = 1.0

    @property
    def abandono_pct(self) -> float:
        return 100.0 * self.abandonadas / self.contestadas if self.contestadas else 0.0

    def ocupacion(self, p: Parametros) -> float:
        """Fracción del tiempo de los agentes hablando con clientes."""
        return self.tiempo_hablado_s / (p.agentes * p.duracion_s)


def simular(p: Parametros, metodo: str = "predictivo") -> Resultado:
    """`metodo`: "predictivo" (nivel adaptativo), "proporcional" (fijo en
    nivel_inicial) o "progresivo" (una llamada por agente)."""
    rng = random.Random(p.semilla)
    t = 0.0
    libre_desde = [0.0] * p.agentes  # cuándo quedó libre; None = ocupado
    ocupado_hasta: list[float | None] = [None] * p.agentes
    en_llamada_desde: list[float | None] = [None] * p.agentes
    timbrando: list[tuple[float, bool]] = []  # (fin del timbre, contesta)
    espera: list[float] = []  # límite de cada cliente contestado sin agente
    ventana = predictivo.Ventana()
    nivel = p.nivel_inicial
    factor = predictivo.FACTOR_INICIAL
    ultimo_ajuste = -1e9
    intentos = contestadas = abandonadas = conversaciones = 0
    hablado = espera_ag = 0.0
    abandonadas_dia = contestadas_dia = 0

    def asignar(ahora: float) -> bool:
        nonlocal conversaciones, hablado, espera_ag
        libres = [i for i in range(p.agentes) if ocupado_hasta[i] is None]
        if not libres:
            return False
        i = min(libres, key=lambda k: libre_desde[k])
        esperado = ahora - libre_desde[i]
        espera_ag += esperado
        ventana.esperas_agente.append((ahora, esperado))
        # Gamma con forma 4 (variación del 50 %): más parecido a llamadas
        # reales que una exponencial, que hace imposible prever el final.
        conversacion = rng.gammavariate(4.0, p.aht_s / 4.0)
        ventana.conversaciones.append((ahora, conversacion))
        hablado += conversacion
        conversaciones += 1
        ocupado_hasta[i] = ahora + conversacion + p.acw_s
        en_llamada_desde[i] = ahora
        return True

    while t < p.duracion_s:
        # Agentes que terminan.
        for i in range(p.agentes):
            if ocupado_hasta[i] is not None and ocupado_hasta[i] <= t:
                ocupado_hasta[i] = None
                en_llamada_desde[i] = None
                libre_desde[i] = t
        # Timbres que terminan.
        siguen = []
        for fin, contesta in timbrando:
            if fin > t:
                siguen.append((fin, contesta))
                continue
            ventana.resueltas.append(t)
            if contesta:
                contestadas += 1
                contestadas_dia += 1
                ventana.contestadas.append(t)
                espera.append(t + p.temporizador_s)
        timbrando = siguen
        # Clientes esperando: agente o abandono.
        quedan = []
        for limite in sorted(espera):
            if asignar(t):
                continue
            if t >= limite:
                abandonadas += 1
                abandonadas_dia += 1
                ventana.abandonadas.append(t)
            else:
                quedan.append(limite)
        espera = quedan
        # Ajuste del nivel (cada 10 s, como el motor real).
        if metodo == "predictivo" and t - ultimo_ajuste >= 10:
            ultimo_ajuste = t
            dia = 100.0 * abandonadas_dia / contestadas_dia if contestadas_dia >= predictivo.MINIMO_MUESTRA else None
            factor = predictivo.ajustar_factor(factor, dia, ventana.abandono(t), p.objetivo_pct,
                                               ventana.espera_agente(t))
        # Lanzar.
        listos = sum(1 for i in range(p.agentes) if ocupado_hasta[i] is None)
        aht, ring = ventana.aht(t), (p.ring_min_s + p.ring_max_s) / 2
        pronto = sum(
            1 for i in range(p.agentes)
            if ocupado_hasta[i] is not None and en_llamada_desde[i] is not None
            and t - en_llamada_desde[i] >= max(0.0, aht - ring)
        )
        if metodo == "progresivo":
            n = max(0, listos - len(timbrando) - len(espera))
        elif metodo == "predictivo":
            n = predictivo.a_lanzar_predictivo(listos, pronto, len(timbrando), len(espera), ventana.contacto(t),
                                               p.objetivo_pct / factor, p.nivel_max)
            libres = listos - len(espera)
            nivel = round((len(timbrando) + n) / libres, 2) if libres > 0 else nivel
        else:
            n = predictivo.a_lanzar(listos, pronto, len(timbrando), len(espera), nivel)
        for _ in range(n):
            intentos += 1
            timbrando.append((t + rng.uniform(p.ring_min_s, p.ring_max_s), rng.random() < p.contacto))
        t += p.paso_s

    return Resultado(metodo, intentos, contestadas, abandonadas, conversaciones, hablado, espera_ag, nivel, factor)


if __name__ == "__main__":  # pragma: no cover
    parametros = Parametros()
    for metodo in ("progresivo", "proporcional", "predictivo"):
        r = simular(parametros if metodo != "proporcional" else Parametros(nivel_inicial=2.0), metodo)
        print(
            f"{metodo:12} intentos={r.intentos:5} contestadas={r.contestadas:4} "
            f"abandono={r.abandono_pct:5.2f}% ocupación={100 * r.ocupacion(parametros):5.1f}% "
            f"conversaciones={r.conversaciones:4} nivel={r.nivel_final}"
        )
