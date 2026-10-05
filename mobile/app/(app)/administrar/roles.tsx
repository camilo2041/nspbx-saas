import { useState } from "react";
import { ScrollView, Switch, Text, View } from "react-native";

import { peticion } from "@/src/api/client";
import { invalidar, useDatos } from "@/src/datos";
import { Aviso, Esqueleto, Hoja, Pantalla } from "@/src/gestion";
import { exito, fallo } from "@/src/haptico";
import { useColores } from "@/src/tema";
import { Boton, FilaMenu, Pildora, Seccion } from "@/src/ui";

interface Opcion {
  value: string;
  label: string;
  description?: string;
}

interface Datos {
  roles: Opcion[];
  permisos: Opcion[];
  matriz: Record<string, Record<string, boolean>>;
  fijos: Record<string, string[]>;
  por_defecto: Record<string, string[]>;
}

export default function Roles() {
  const c = useColores();
  const { datos, cargando, refrescando, error, recargar } = useDatos<Datos>("/api/role-permissions", { ttl: 10_000 });
  const [rol, setRol] = useState<Opcion | null>(null);
  const [marcas, setMarcas] = useState<Record<string, boolean>>({});
  const [guardando, setGuardando] = useState(false);
  const [errorHoja, setErrorHoja] = useState("");
  const [aviso, setAviso] = useState("");

  const abrir = (r: Opcion) => {
    setRol(r);
    setMarcas({ ...(datos?.matriz[r.value] ?? {}) });
    setErrorHoja("");
  };

  const guardar = async () => {
    if (!rol) return;
    setGuardando(true);
    setErrorHoja("");
    try {
      await peticion("/api/role-permissions", { method: "PUT", body: { role: rol.value, permisos: marcas } });
      exito();
      setAviso(`Permisos de ${rol.label} guardados. Los usuarios con ese rol los ven al volver a entrar o al refrescar.`);
      setRol(null);
      // Se recarga en vez de confiar en lo local: el servidor ignora las casillas fijas.
      invalidar("/api/role-permissions");
      recargar();
    } catch (err) {
      fallo();
      setErrorHoja(err instanceof Error ? err.message : "No se pudo guardar");
    } finally {
      setGuardando(false);
    }
  };

  const cambiados = (r: string) =>
    (datos?.permisos ?? []).filter((p) => !(datos?.fijos[r] ?? []).includes(p.value) && (datos?.matriz[r]?.[p.value] ?? false) !== (datos?.por_defecto[r] ?? []).includes(p.value)).length;

  const hayCambios = !!rol && !!datos && datos.permisos.some((p) => (marcas[p.value] ?? false) !== (datos.matriz[rol.value]?.[p.value] ?? false));

  return (
    <>
      <Pantalla refrescando={refrescando} onRefrescar={recargar}>
        <Text style={{ fontSize: 13, color: c.textoSecundario, lineHeight: 18 }}>
          Qué puede hacer cada rol en esta empresa. Los cambios afectan a todos sus usuarios.
        </Text>
        {aviso ? <Aviso tono="ok" texto={aviso} /> : null}
        {error && !datos ? <Aviso texto={error} /> : null}
        {cargando && !datos ? <Esqueleto alto={200} /> : null}
        {datos ? (
          <Seccion titulo="Roles">
            {datos.roles.map((r, i) => {
              const n = cambiados(r.value);
              const activos = datos.permisos.filter((p) => datos.matriz[r.value]?.[p.value]).length;
              return (
                <FilaMenu
                  key={r.value}
                  titulo={r.label}
                  detalle={r.description ?? `${activos} de ${datos.permisos.length} permisos`}
                  icono="llave"
                  tono="marca"
                  valor={n ? undefined : `${activos}/${datos.permisos.length}`}
                  derecha={n ? <Pildora texto={`${n} cambio(s)`} tono="aviso" /> : undefined}
                  onPress={() => abrir(r)}
                  ultima={i === datos.roles.length - 1}
                />
              );
            })}
          </Seccion>
        ) : null}
        <Text style={{ fontSize: 12, color: c.textoSecundario, lineHeight: 17 }}>
          Algunos permisos del Administrador son fijos a propósito: sin ellos, un cambio equivocado dejaría a la empresa sin nadie que
          pueda revertirlo. Gestionar empresas pertenece al rol de plataforma y no se configura desde una empresa.
        </Text>
      </Pantalla>

      <Hoja visible={!!rol} titulo={rol?.label ?? ""} onCerrar={() => setRol(null)}>
        {rol && datos ? (
          <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 4, gap: 10 }}>
            {datos.permisos.map((p) => {
              const fijo = (datos.fijos[rol.value] ?? []).includes(p.value);
              const activo = marcas[p.value] ?? false;
              const porDefecto = (datos.por_defecto[rol.value] ?? []).includes(p.value);
              return (
                <View key={p.value} style={{ flexDirection: "row", alignItems: "center", gap: 12, opacity: fijo ? 0.55 : 1 }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: 14.5, fontWeight: "600", color: c.texto }}>{p.label}</Text>
                    {p.description ? <Text style={{ fontSize: 12, color: c.textoSecundario, marginTop: 2 }}>{p.description}</Text> : null}
                    {fijo ? (
                      <Text style={{ fontSize: 11.5, color: c.textoSecundario, marginTop: 2 }}>Fijo</Text>
                    ) : activo !== porDefecto ? (
                      <View style={{ marginTop: 4 }}>
                        <Pildora texto={activo ? "Agregado" : "Quitado"} tono="aviso" />
                      </View>
                    ) : null}
                  </View>
                  <Switch
                    value={activo}
                    disabled={fijo}
                    onValueChange={(x) => setMarcas((m) => ({ ...m, [p.value]: x }))}
                    trackColor={{ true: c.marca, false: c.bordeFuerte }}
                    thumbColor="#fff"
                  />
                </View>
              );
            })}
            {errorHoja ? <Aviso texto={errorHoja} /> : null}
            <Boton titulo="Guardar" onPress={guardar} cargando={guardando} deshabilitado={!hayCambios} style={{ marginTop: 6 }} />
          </ScrollView>
        ) : null}
      </Hoja>
    </>
  );
}
