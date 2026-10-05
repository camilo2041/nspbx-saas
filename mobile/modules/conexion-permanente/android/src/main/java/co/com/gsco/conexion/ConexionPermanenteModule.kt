package co.com.gsco.conexion

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class ConexionPermanenteModule : Module() {
  private val contexto: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  override fun definition() = ModuleDefinition {
    Name("ConexionPermanente")

    Events("latido")

    OnCreate {
      Latido.emisor = { sendEvent("latido", mapOf<String, Any?>()) }
    }

    OnDestroy {
      Latido.emisor = null
    }

    /** Arranca (o actualiza) el servicio. Llamarlo con la app en pantalla:
     * Android 12+ no deja iniciar un servicio en primer plano desde atrás. */
    Function("iniciar") { titulo: String, texto: String, despierto: Boolean ->
      val intent = Intent(contexto, ServicioConexion::class.java)
        .putExtra(ServicioConexion.EXTRA_TITULO, titulo)
        .putExtra(ServicioConexion.EXTRA_TEXTO, texto)
        .putExtra(ServicioConexion.EXTRA_DESPIERTO, despierto)
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        contexto.startForegroundService(intent)
      } else {
        contexto.startService(intent)
      }
      Unit
    }

    Function("actualizar") { titulo: String, texto: String ->
      ServicioConexion.actualizar(contexto, titulo, texto)
    }

    Function("detener") {
      contexto.stopService(Intent(contexto, ServicioConexion::class.java))
      Unit
    }

    Function("activa") {
      ServicioConexion.activo
    }

    /** ¿La app está fuera del ahorro de batería? Sin eso, en reposo Android
     * le corta la red y la conexión con la central se cae. */
    Function("sinRestriccionBateria") {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return@Function true
      val pm = contexto.getSystemService(Context.POWER_SERVICE) as PowerManager
      pm.isIgnoringBatteryOptimizations(contexto.packageName)
    }

    /** Pide al usuario sacar la app del ahorro de batería (diálogo del sistema). */
    Function("pedirSinRestriccionBateria") {
      // Sin `return@Function` a secas: Expo espera `() -> Any?` y un return
      // vacío es Unit (no compila).
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
        val directo = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
          .setData(Uri.parse("package:${contexto.packageName}"))
          .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
          contexto.startActivity(directo)
        } catch (_: Exception) {
          // Algunas marcas no tienen ese diálogo: se abre la lista general.
          contexto.startActivity(
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
          )
        }
      }
      null
    }

    /** Ajustes de la app (para el ahorro de batería propio de cada marca). */
    Function("abrirAjustesApp") {
      contexto.startActivity(
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
          .setData(Uri.parse("package:${contexto.packageName}"))
          .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
      )
    }
  }
}
