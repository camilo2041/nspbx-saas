/**
 * Colores del panel web (frontend/app/globals.css, modo claro) para que la app
 * se vea como parte del mismo sistema: naranja de marca, fondo azulado claro,
 * tarjetas blancas con borde fino.
 *
 * Se fijan explícitos (texto, placeholder, fondo) porque la app fuerza tema
 * claro y varios Android, con el sistema en modo oscuro, pintan el texto y el
 * placeholder de un TextInput con colores del tema del sistema: sobre fondo
 * blanco el placeholder quedaba casi invisible.
 */
export const colores = {
  fondo: "#f2f5fb",
  superficie: "#ffffff",
  superficie2: "#f8fafc",
  superficie3: "#eff3f9",
  borde: "#e5e9f0",
  bordeFuerte: "#cdd5e1",

  texto: "#0f172a",
  textoSuave: "#334155",
  textoSecundario: "#64748b",
  placeholder: "#94a3b8",

  marca: "#ea580c",
  marcaSuave: "#fff7ed",
  marcaTexto: "#c2410c",
  sobreMarca: "#ffffff",

  ok: "#059669",
  okSuave: "#ecfdf5",
  okTexto: "#047857",

  aviso: "#d97706",
  avisoSuave: "#fffbeb",
  avisoTexto: "#b45309",

  peligro: "#e11d48",
  peligroSuave: "#fff1f2",
  peligroTexto: "#be123c",

  info: "#0284c7",
  infoSuave: "#f0f9ff",
  infoTexto: "#0369a1",
};

export const radios = { chico: 10, medio: 14, grande: 20 };

export const sombra = {
  shadowColor: "#0f172a",
  shadowOpacity: 0.08,
  shadowRadius: 10,
  shadowOffset: { width: 0, height: 4 },
  elevation: 2,
};

// Compatibilidad con los nombres que ya usaban las pantallas.
export const alias = {
  primario: colores.marca,
  error: colores.peligro,
  borde: colores.borde,
};
