# Puesta en marcha de la app móvil

Esta app reutiliza el mismo softphone WebRTC que el panel (`sip.js` contra
FreeSWITCH) y agrega timbrado nativo (CallKit en iOS, ConnectionService en
Android) para que una llamada entrante suene igual que una llamada de
teléfono normal, aunque la app esté en segundo plano o cerrada. Para que
esa parte funcione hacen falta credenciales que solo vos podés generar
(no son secretos que yo pueda inventar ni conseguir): una cuenta de Apple
Developer y un proyecto de Firebase. Sin ellas, la app compila y sirve
igual para llamar/contestar **con la app abierta** y ver métricas — lo
único que no funciona es el timbrado con la app en segundo plano.

## 1. Antes de compilar: identificadores propios

`app.json` trae un bundle id / package de relleno (`co.com.gsco.nspbx`).
Cambialo por el que vayas a usar de verdad en `ios.bundleIdentifier` y
`android.package` — tiene que coincidir con lo que registres en Apple
Developer y Firebase en los pasos siguientes.

## 2. iOS — Apple Developer (push de voz / CallKit)

1. Necesitás una cuenta de [Apple Developer Program](https://developer.apple.com/programs/) (de pago, US$99/año) — sin esto no hay forma de firmar ni distribuir la app, con o sin llamadas.
2. En **Certificates, Identifiers & Profiles**, creá un **App ID** con el bundle id elegido arriba, con el capability **Push Notifications** habilitado.
3. En **Keys**, creá una **APNs Auth Key** (archivo `.p8`) — sirve para todos tus apps, no hace falta un certificado por app. Anotá:
   - El **Key ID** (10 caracteres).
   - Tu **Team ID** (arriba a la derecha del portal).
   - El contenido del archivo `.p8` (empieza con `-----BEGIN PRIVATE KEY-----`).
4. En el backend, definí estas variables de entorno (ver `backend/app/core/config.py`):
   ```
   APNS_KEY_ID=...
   APNS_TEAM_ID=...
   APNS_AUTH_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
   APNS_BUNDLE_ID=co.com.gsco.nspbx   # el mismo que en app.json, SIN ".voip"
   APNS_USE_SANDBOX=true              # true en desarrollo/TestFlight interno, false en producción
   ```

## 3. Android — Firebase (push de voz)

1. Creá un proyecto en la [consola de Firebase](https://console.firebase.google.com/) (gratis).
2. Agregá una app Android con el `android.package` elegido arriba. Descargá el `google-services.json` que te da Firebase.
3. Poné ese archivo en `mobile/google-services.json` y agregá esta línea a `app.json`:
   ```jsonc
   "android": {
     "googleServicesFile": "./google-services.json",
     ...
   }
   ```
4. En **Configuración del proyecto → Cuentas de servicio**, generá una clave privada nueva (JSON). En el backend:
   ```
   FCM_PROJECT_ID=tu-proyecto-firebase
   FCM_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"...", ...}'   # el JSON completo, en una sola línea
   ```

## 4. Compilar (EAS Build — necesario en Windows)

Esta app usa módulos nativos (`expo-callkit-telecom`, `@livekit/react-native-webrtc`), así que **no funciona en Expo Go**: hace falta un build de desarrollo propio.

```bash
npm install -g eas-cli
eas login          # cuenta gratuita de Expo (expo.dev)
eas build:configure
eas build --profile development --platform android
eas build --profile development --platform ios
```

En Windows no hay forma de compilar ni firmar la app de iOS localmente (necesita Xcode/macOS) — por eso el build de iOS se hace en la nube con `eas build`, que no requiere una Mac. Una vez instalado el build de desarrollo en el teléfono:

```bash
npm run start   # expo start --dev-client
```

Para producción, `eas build --profile production --platform ios|android` y `eas submit` para subirlo a las tiendas (requiere las cuentas de desarrollador de cada plataforma).

## 5. Conectarse a tu empresa

En la pantalla de login, el primer campo pide la URL del panel de tu empresa (la misma que usás en el navegador, ej. `midominio.pbx.ejemplo.com`) — de ahí la app deduce tanto la API como el subdominio que identifica a tu empresa (ver `docs/arquitectura-multitenant.md`). Después, usuario y contraseña, igual que en el panel web.

## Límite conocido

Mantener la conexión SIP viva indefinidamente con la app en segundo plano no es algo que iOS/Android permitan de forma confiable solo con JavaScript — por eso existe todo el mecanismo de push de voz: el sistema operativo despierta la app justo cuando entra una llamada, no todo el tiempo. Con buena señal y las credenciales de arriba bien puestas, el timbrado en segundo plano funciona, pero no es tan instantáneo ni 100% infalible como el de una app de telefonía nativa del operador — la latencia del push (típicamente menos de un segundo, a veces más) se suma al tiempo de reconexión SIP antes de que timbre.
