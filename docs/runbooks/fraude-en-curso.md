# Runbook 1 — Fraude telefónico en curso

Alguien está haciendo llamadas salientes que la empresa no autorizó,
normalmente a destinos internacionales o premium, de madrugada y en ráfaga.
Cada minuto cuesta dinero: **contener primero**.

## Síntomas

- Alerta "Pico de salientes", "Salientes de madrugada" o "Destino
  internacional nuevo" (panel o webhook).
- Aviso del proveedor SIP por consumo anómalo o saldo agotado.
- "Cupo diario de minutos agotado" en Ajustes de una empresa.
- Llamadas en el historial a números que nadie reconoce.

## Confirmar (2 minutos)

1. Empresas → Alertas: qué empresa y desde cuándo.
2. Llamadas de esa empresa, filtrando salientes: ¿destinos raros, muchas
   llamadas cortas o largas seguidas, desde qué extensión?
3. Ajustes → estado de salientes: minutos de hoy contra el cupo.

## Contener (5 minutos)

En este orden, hasta que pare:

1. **Cortar las salientes de esa empresa**: Empresas → *Cortar salientes*.
   La empresa no puede deshacerlo. Corta toda llamada **nueva** en los tres
   caminos (teléfonos, clic para llamar, campañas).
2. Si son varias empresas, o no se sabe cuál: Empresas → *Cortar todas las
   salientes*.
3. Las llamadas **en curso** no se cortan solas (terminan por la duración
   máxima). Para colgarlas ya, en el servidor:
   ```bash
   docker exec -it nspbx_freeswitch fs_cli -x "show calls" | grep -i <prefijo-o-dominio-de-la-empresa>
   docker exec -it nspbx_freeswitch fs_cli -x "uuid_kill <uuid>"
   ```
4. Si la llamada sale con una extensión concreta: desactivarla
   (Extensiones → editar → deshabilitar) y **cambiarle la contraseña**.
5. Avisar al proveedor SIP: muchos bloquean destinos o revierten cargos si
   se avisa rápido.

## Investigar

- **¿Por dónde entró?**
  - Extensión con contraseña débil: Seguridad → Contraseñas SIP débiles, y
    fail2ban (Seguridad → Bloqueos) por intentos de registro previos.
  - Cuenta del panel: Auditoría → cambios recientes en rutas salientes,
    *permitir internacional*, países, topes o troncales.
    ```
    GET /api/plataforma/auditoria?accion=outbound-routes
    GET /api/plataforma/auditoria?accion=system/settings
    ```
  - Campaña con números cargados por alguien no autorizado: Auditoría →
    `POST /api/campaigns/{campaign_id}/numbers`.
- **¿Cuánto se perdió?** Minutos por troncal del período en el historial de
  llamadas; contrastar con la factura del proveedor.

## Recuperar

1. Cerrar la puerta de entrada: contraseña SIP nueva (vacía = el sistema
   genera una fuerte), credencial del panel rotada (runbook 2), regla de
   salida o permiso internacional revertido.
2. Revisar que *Países permitidos* tenga solo lo necesario.
3. Reactivar salientes (Empresas → *Reactivar salientes*) y hacer una
   llamada de prueba.

## Cerrar

Informe: desde cuándo, cuántos minutos y a qué destinos, cómo entró, qué
detectó primero (alerta, cupo, proveedor) y con cuánto retraso. Si una
alerta debió saltar antes, ajustar sus umbrales en `services/alertas.py` y
agregar la prueba.
