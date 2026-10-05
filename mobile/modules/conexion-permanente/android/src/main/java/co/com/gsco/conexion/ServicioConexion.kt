package co.com.gsco.conexion

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock

/**
 * Mantiene viva la app (y con ella el registro SIP que hace sip.js en JS)
 * mientras está en segundo plano, para recibir llamadas sin push.
 *
 * - Servicio en primer plano con una notificación fija: Android no mata el
 *   proceso ni le corta la red.
 * - Wi-Fi despierto con la pantalla apagada (si no, el teléfono la apaga y
 *   la conexión con la central se cae).
 * - Un latido cada [INTERVALO_MS] con AlarmManager, que sí suena en reposo
 *   profundo (Doze): despierta el procesador unos segundos y le avisa a JS
 *   para que renueve el registro antes de que venza.
 * - Opcional: el procesador despierto todo el tiempo (más batería) para los
 *   teléfonos que igual pierden llamadas.
 */
class ServicioConexion : Service() {
  private var wifi: WifiManager.WifiLock? = null
  private var despierto: PowerManager.WakeLock? = null

  override fun onBind(intent: Intent?): IBinder? = null

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    // Si Android recrea el servicio sin la app (proceso muerto), no hay JS que
    // mantenga el registro: mejor no mostrar «conectada» en falso.
    if (intent == null) {
      stopSelf()
      return START_NOT_STICKY
    }
    val titulo = intent.getStringExtra(EXTRA_TITULO) ?: "Central conectada"
    val texto = intent.getStringExtra(EXTRA_TEXTO) ?: "Lista para recibir llamadas"
    val notificacion = notificacion(this, titulo, texto)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
      startForeground(ID_NOTIFICACION, notificacion, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
    } else {
      startForeground(ID_NOTIFICACION, notificacion)
    }
    activo = true
    retenerWifi()
    retenerProcesador(intent.getBooleanExtra(EXTRA_DESPIERTO, false))
    programarLatido(this)
    return START_NOT_STICKY
  }

  override fun onDestroy() {
    activo = false
    cancelarLatido(this)
    wifi?.let { if (it.isHeld) it.release() }
    wifi = null
    retenerProcesador(false)
    super.onDestroy()
  }

  @Suppress("DEPRECATION")
  private fun retenerWifi() {
    if (wifi?.isHeld == true) return
    val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
    // FULL_HIGH_PERF quedó obsoleto en Android 14, pero sigue siendo el que
    // mantiene la Wi-Fi con la pantalla apagada; LOW_LATENCY solo actúa con
    // la app visible.
    wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "nspbx:conexion").apply {
      setReferenceCounted(false)
      acquire()
    }
  }

  private fun retenerProcesador(si: Boolean) {
    if (si) {
      if (despierto?.isHeld == true) return
      val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
      despierto = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "nspbx:siempre").apply {
        setReferenceCounted(false)
        acquire()
      }
    } else {
      despierto?.let { if (it.isHeld) it.release() }
      despierto = null
    }
  }

  companion object {
    const val EXTRA_TITULO = "titulo"
    const val EXTRA_TEXTO = "texto"
    const val EXTRA_DESPIERTO = "despierto"
    private const val CANAL = "nspbx_conexion"
    private const val ID_NOTIFICACION = 7324
    private const val CODIGO_LATIDO = 7325

    /** Android no deja que una alarma «en reposo» suene más de una vez cada ~9 min. */
    const val INTERVALO_MS = 9L * 60 * 1000

    @Volatile
    var activo = false
      private set

    fun notificacion(contexto: Context, titulo: String, texto: String): Notification {
      val nm = contexto.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm.getNotificationChannel(CANAL) == null) {
        val canal = NotificationChannel(CANAL, "Conexión con la central", NotificationManager.IMPORTANCE_LOW).apply {
          description = "Mantiene la app conectada para recibir llamadas con la pantalla apagada"
          setShowBadge(false)
        }
        nm.createNotificationChannel(canal)
      }
      val abrir = contexto.packageManager.getLaunchIntentForPackage(contexto.packageName)?.let {
        PendingIntent.getActivity(contexto, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
      }
      val icono = contexto.resources.getIdentifier("notification_icon", "drawable", contexto.packageName)
        .takeIf { it != 0 } ?: android.R.drawable.sym_action_call
      val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        Notification.Builder(contexto, CANAL)
      } else {
        @Suppress("DEPRECATION")
        Notification.Builder(contexto)
      }
      return b.setContentTitle(titulo)
        .setContentText(texto)
        .setSmallIcon(icono)
        .setOngoing(true)
        .setShowWhen(false)
        .setCategory(Notification.CATEGORY_SERVICE)
        .apply { if (abrir != null) setContentIntent(abrir) }
        .build()
    }

    /** Cambia el texto de la notificación sin reiniciar el servicio. */
    fun actualizar(contexto: Context, titulo: String, texto: String) {
      if (!activo) return
      val nm = contexto.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      nm.notify(ID_NOTIFICACION, notificacion(contexto, titulo, texto))
    }

    private fun intentLatido(contexto: Context): PendingIntent =
      PendingIntent.getBroadcast(
        contexto,
        CODIGO_LATIDO,
        Intent(contexto, ReceptorLatido::class.java),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
      )

    fun programarLatido(contexto: Context) {
      val am = contexto.getSystemService(Context.ALARM_SERVICE) as AlarmManager
      val cuando = SystemClock.elapsedRealtime() + INTERVALO_MS
      // Inexacta pero «allow while idle»: suena en Doze y no pide el permiso
      // de alarmas exactas (que Android 14 niega por defecto).
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
        am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, cuando, intentLatido(contexto))
      } else {
        am.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, cuando, intentLatido(contexto))
      }
    }

    fun cancelarLatido(contexto: Context) {
      val am = contexto.getSystemService(Context.ALARM_SERVICE) as AlarmManager
      am.cancel(intentLatido(contexto))
    }
  }
}
