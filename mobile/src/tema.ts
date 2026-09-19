/**
 * Colores fijos de la app. Se definen explícitos (texto, placeholder, fondo)
 * porque la app fuerza tema claro (`userInterfaceStyle: "light"` en
 * app.json) pero varios Android —sobre todo con el sistema en modo
 * oscuro— pintan el texto y el placeholder de un TextInput con colores del
 * tema del sistema: sobre fondo blanco el placeholder queda casi invisible.
 */
export const colores = {
  fondo: "#ffffff",
  texto: "#111111",
  textoSecundario: "#555555",
  placeholder: "#8a8a8a",
  borde: "#c9c9c9",
  primario: "#1c6dd0",
  error: "#c0392b",
};
