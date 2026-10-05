package co.com.gsco.conexion

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.PowerManager

/**
 * El latido de [ServicioConexion]: mantiene el procesador despierto unos
 * segundos para que JS renueve el registro SIP, y programa el siguiente.
 */
class ReceptorLatido : BroadcastReceiver() {
  override fun onReceive(contexto: Context, intent: Intent) {
    if (!ServicioConexion.activo) return
    val pm = contexto.getSystemService(Context.POWER_SERVICE) as PowerManager
    // Se suelta solo: basta para reconectar y registrar (o para que JS note
    // que no hay red y lo reintente en el próximo latido).
    pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "nspbx:latido").acquire(DURACION_MS)
    Latido.emitir()
    ServicioConexion.programarLatido(contexto)
  }

  companion object {
    const val DURACION_MS = 20_000L
  }
}

/** Puente del latido hacia el módulo (y de ahí a JS), si la app está viva. */
object Latido {
  @Volatile
  var emisor: (() -> Unit)? = null

  fun emitir() {
    emisor?.invoke()
  }
}
