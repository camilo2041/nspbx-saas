"""Fase 7: prueba de carga liviana (la completa es carga/prueba_carga.py).

Lo que importa en CI es la CORRECCIÓN bajo carga, no el número exacto (el
runner varía): con muchos clientes contestando a la vez, en paralelo, ningún
agente recibe dos llamadas, todos los libres reciben una y los que sobran
esperan. Las cotas de tiempo son holgadas: solo atrapan una regresión de
orden de magnitud (como los 25 s que tardaba el reporte de agentes de una
semana antes de agregar en SQL).
"""

from datetime import date, timedelta

from carga import prueba_carga as pc


async def test_motor_y_reportes_bajo_carga(mundo):
    ctx = await pc.sembrar(40, n_leads=200)
    try:
        m = await pc.medir_motor(ctx)
        assert m["lanzadas"] > m["agentes"]  # con 30 % de contacto, sobremarca
        assert m["asignadas"] == m["agentes"] == m["agentes_en_llamada"] == 40
        assert m["agentes_con_dos_llamadas"] == 0
        assert m["en_espera"] == m["contestan"] - m["agentes"]
        assert m["vuelta_s"] < 5 and m["asignar_total_s"] < 15

        s = await pc.medir_supervision(ctx, repeticiones=2)
        assert s["agentes_conectados"] == 40 and s["agentes"] < 2000

        hasta = date.today() - timedelta(days=1)
        h = await pc.sembrar_historia(ctx, dias=2, llamadas_por_agente_dia=40, hasta=hasta)
        assert h["llamadas"] == 40 * 2 * 40
        r = await pc.medir_reportes(ctx, hasta - timedelta(days=1), hasta)
        assert all(ms < 10_000 for ms in r.values()), r
    finally:
        await pc.limpiar(ctx)
