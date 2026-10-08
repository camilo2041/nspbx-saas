import { useCallback, useState } from "react";

/**
 * La página (offset) de una lista que vuelve sola a la primera cuando
 * cambian los filtros. Antes se hacía con un efecto que ponía el offset en
 * 0 después de cambiar un filtro: se pintaba una vez con la página vieja
 * (y se pedía al backend) antes de corregirse. Aquí el offset se guarda junto
 * con los filtros con los que se eligió; si los filtros cambian, vale 0.
 */
export function useOffsetPorFiltro(filtros: unknown[]): [number, (offset: number) => void] {
  const clave = JSON.stringify(filtros);
  const [estado, setEstado] = useState({ clave, offset: 0 });
  const offset = estado.clave === clave ? estado.offset : 0;
  const setOffset = useCallback((nuevo: number) => setEstado({ clave, offset: nuevo }), [clave]);
  return [offset, setOffset];
}
