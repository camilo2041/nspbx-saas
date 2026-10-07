# Desbloquear una IP de fail2ban

Caso típico: la oficina de un cliente se equivocó varias veces de clave SIP y
fail2ban bloqueó su IP para todo el servidor.

## Desde el panel

Plataforma › Empresas › «IP bloqueadas (fail2ban)» › Desbloquear. Solo lo ve
el rol de plataforma; el administrador de una empresa ve los bloqueos en
Seguridad, pero no puede quitarlos.

El panel no toca el cortafuegos: deja un pedido (tabla `desbloqueos_ip`) y el
script del host lo ejecuta en menos de un minuto. Si un pedido lleva más de 5
minutos pendiente, la tarjeta lo avisa: el script no está corriendo.

## Instalar el script (una vez, en el host, como root)

```bash
crontab -e
# agrega:
* * * * *  cd /ruta/nspbx-saas && bash scripts/fail2ban-desbloquear.sh >> /var/log/nspbx-desbloqueos.log 2>&1
```

Lo único que hace con fail2ban es `fail2ban-client set <jail> unbanip <ip>`, y
vuelve a validar el jail y la IP que le pasa el backend. Un backend
comprometido solo puede pedir que se desbloquee una IP que ya está bloqueada.

## A mano, sin panel

```bash
fail2ban-client status                 # los jails
fail2ban-client status <jail>          # quién está bloqueado
fail2ban-client set <jail> unbanip <ip>
```

Si la IP vuelve a fallar, fail2ban la bloquea otra vez: hay que corregir la
clave del teléfono o del softphone que la está usando.
