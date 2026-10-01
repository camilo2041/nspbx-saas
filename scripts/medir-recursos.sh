#!/usr/bin/env bash
# Mide el pico de memoria, CPU y procesos de cada contenedor durante un
# tiempo (idealmente un día de campaña) y propone los topes del .env.
#
#   bash scripts/medir-recursos.sh            # 24 h, una muestra cada 10 s
#   bash scripts/medir-recursos.sh 8 5        # 8 h, cada 5 s
#   bash scripts/medir-recursos.sh --resumen recursos-2026-10-01.csv
#
# Para un día entero, correrlo desconectado de la sesión:
#   nohup bash scripts/medir-recursos.sh 24 > /dev/null 2>&1 &
#
# Solo lee (`docker stats`): no cambia nada. Los topes se aplican copiando
# las líneas sugeridas al .env y con `docker compose up -d`.
#
# Criterio: 2× el pico medido, nunca menos de un piso por servicio, redondeado
# hacia arriba a 256 MB. FreeSWITCH y Postgres se informan pero no llevan
# tope a propósito: si se quedaran sin memoria se cortarían las llamadas o la
# base (ver docs/seguridad-y-robustez.md, §5.13).
set -euo pipefail
cd "$(dirname "$0")/.."

resumir() {
  python3 - "$1" <<'PY'
import csv, math, sys

def mb(texto):
    """'123.4MiB' / '1.2GiB' / '900kB' -> MB."""
    texto = texto.strip()
    for sufijo, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("GB", 1000 / 1.048576), ("MB", 1 / 1.048576), ("kB", 1 / 1048.576), ("B", 1 / 1048576)):
        if texto.endswith(sufijo):
            return float(texto[: -len(sufijo)]) * factor
    return 0.0

con_tope = {"nspbx_backend": ("BACKEND_MEM_LIMIT", 512), "nspbx_voicebot": ("VOICEBOT_MEM_LIMIT", 512),
            "nspbx_frontend": ("FRONTEND_MEM_LIMIT", 256)}
picos = {}
for fila in csv.reader(open(sys.argv[1])):
    if len(fila) != 6 or fila[0] == "hora":
        continue
    _, nombre, mem, cpu, pids, _ = fila
    usado, _, limite = mem.partition("/")
    p = picos.setdefault(nombre, {"mem": 0.0, "cpu": 0.0, "pids": 0, "limite": mb(limite), "muestras": 0})
    p["mem"] = max(p["mem"], mb(usado))
    p["cpu"] = max(p["cpu"], float(cpu.rstrip("%") or 0))
    p["pids"] = max(p["pids"], int(pids or 0))
    p["muestras"] += 1

if not picos:
    sys.exit("No hay muestras en el archivo.")
print(f"{'contenedor':<20} {'pico memoria':>13} {'tope actual':>12} {'pico CPU':>9} {'procesos':>9}  muestras")
sugerencias = []
for nombre in sorted(picos):
    p = picos[nombre]
    tope = f"{p['limite']:.0f} MB" if nombre in con_tope else "sin tope"
    print(f"{nombre:<20} {p['mem']:>10.0f} MB {tope:>12} {p['cpu']:>8.0f}% {p['pids']:>9}  {p['muestras']}")
    if nombre in con_tope:
        variable, piso = con_tope[nombre]
        propuesto = max(piso, math.ceil(2 * p["mem"] / 256) * 256)
        sugerencias.append(f"{variable}={propuesto}m")
        if p["mem"] > 0.8 * p["limite"]:
            print(f"  ! {nombre} llegó al {100 * p['mem'] / p['limite']:.0f}% de su tope")
        if p["pids"] > 400:
            print(f"  ! {nombre} llegó a {p['pids']} procesos de 512 (pids_limit en docker-compose.yml)")
print("\nSugerido para el .env (2× el pico, con piso):")
print("\n".join(sugerencias))
print("\nCon una medición de un día tranquilo esto se queda corto: medí un día de campaña.")
PY
}

if [ "${1:-}" = "--resumen" ]; then
  resumir "${2:?Falta el archivo .csv}"
  exit 0
fi

HORAS="${1:-24}"
INTERVALO="${2:-10}"
ARCHIVO="recursos-$(date +%F-%H%M).csv"
FIN=$(( $(date +%s) + HORAS * 3600 ))
echo "hora,contenedor,memoria,cpu,procesos,red" > "$ARCHIVO"
echo "Midiendo ${HORAS} h (cada ${INTERVALO} s) en $ARCHIVO. Ctrl+C corta y resume lo medido."
trap 'echo; resumir "$ARCHIVO"; exit 0' INT TERM
while [ "$(date +%s)" -lt "$FIN" ]; do
  docker stats --no-stream --format '{{.Name}},{{.MemUsage}},{{.CPUPerc}},{{.PIDs}},{{.NetIO}}' \
    | grep '^nspbx_' | tr -d ' ' | sed "s/^/$(date +%T),/" >> "$ARCHIVO" || true
  sleep "$INTERVALO"
done
resumir "$ARCHIVO"
