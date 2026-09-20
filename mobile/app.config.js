// Envuelve app.json para poder añadir, SOLO si existe, el archivo de Firebase (google-services.json).
//
// Sin ese archivo el push de voz no funciona (ver mobile/SETUP.md): la app compila igual, pero no
// puede recibir llamadas con la pantalla apagada o la app cerrada. Con él, basta con dejarlo en
// mobile/google-services.json (o subirlo a EAS como variable de tipo archivo GOOGLE_SERVICES_JSON)
// y volver a compilar: no hay que tocar nada más.
const fs = require("fs");
const path = require("path");

module.exports = ({ config }) => {
  const enProyecto = path.join(__dirname, "google-services.json");
  const archivo = process.env.GOOGLE_SERVICES_JSON || (fs.existsSync(enProyecto) ? "./google-services.json" : undefined);
  if (!archivo) {
    console.warn("[NSPBX] Sin google-services.json: la app NO recibirá llamadas en segundo plano (ver SETUP.md).");
    return config;
  }
  return { ...config, android: { ...config.android, googleServicesFile: archivo } };
};
