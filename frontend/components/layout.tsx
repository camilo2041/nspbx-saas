"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";

import { AssistantWidget } from "@/components/assistant-widget";
import { CommandPalette } from "@/components/command-palette";
import { FloatingCallWidget } from "@/components/floating-call-widget";
import { IncomingCallBanner } from "@/components/incoming-call-banner";
import { ThemeToggle } from "@/components/theme";
import { AuthProvider, useAuth } from "@/lib/auth";
import { SoftphoneProvider } from "@/lib/softphone-context";
import { PERMISOS } from "@/lib/types";

const icon = (path: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-[18px] w-[18px] shrink-0">
    {path}
  </svg>
);

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  /** Permiso necesario para verlo. null = visible para cualquier sesión. */
  permiso: string | null;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    title: "Operación",
    items: [
      {
        href: "/",
        label: "Dashboard",
        permiso: null,
        icon: icon(
          <>
            <rect x="3" y="3" width="7" height="9" rx="1.5" />
            <rect x="14" y="3" width="7" height="5" rx="1.5" />
            <rect x="14" y="12" width="7" height="9" rx="1.5" />
            <rect x="3" y="16" width="7" height="5" rx="1.5" />
          </>
        ),
      },
      {
        href: "/softphone",
        label: "Softphone",
        permiso: PERMISOS.softphone,
        icon: icon(
          <>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 18v-6a9 9 0 0118 0v6" />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3v5zM3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3v5z"
            />
          </>
        ),
      },
      {
        href: "/calls",
        label: "Llamadas",
        permiso: PERMISOS.llamadasPropias,
        icon: icon(
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 5h5l2 5-3 2a12 12 0 005 5l2-3 5 2v5a1 1 0 01-1 1A17 17 0 013 6a1 1 0 011-1z"
          />
        ),
      },
      {
        href: "/appointments",
        label: "Citas",
        permiso: PERMISOS.citas,
        icon: icon(
          <>
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <path strokeLinecap="round" d="M16 2v4M8 2v4M3 10h18" />
            <path strokeLinecap="round" d="M9 16l2 2 4-4" />
          </>
        ),
      },
      {
        href: "/cobranza",
        label: "Cobranza",
        permiso: PERMISOS.campanas,
        icon: icon(
          <>
            <circle cx="12" cy="12" r="9" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 7v5l3 2" />
          </>
        ),
      },
    ],
  },
  {
    title: "Telefonía",
    items: [
      {
        href: "/extensions",
        label: "Extensiones",
        permiso: PERMISOS.telefonia,
        icon: icon(
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.362 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0122 16.92z"
          />
        ),
      },
      {
        href: "/trunks",
        label: "Troncales",
        permiso: PERMISOS.telefonia,
        icon: icon(
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 2v6M12 16v6M4.93 4.93l4.24 4.24M14.83 14.83l4.24 4.24M2 12h6M16 12h6M4.93 19.07l4.24-4.24M14.83 9.17l4.24-4.24"
          />
        ),
      },
      {
        href: "/inbound-routes",
        label: "Rutas entrantes",
        permiso: PERMISOS.telefonia,
        icon: icon(<path strokeLinecap="round" strokeLinejoin="round" d="M9 5l-7 7 7 7M2 12h20" />),
      },
      {
        href: "/queues",
        label: "Colas",
        permiso: PERMISOS.colas,
        icon: icon(
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m5-5.13a4 4 0 100-8 4 4 0 000 8zm6 5.13a4 4 0 00-3-3.87M9 11.13a4 4 0 00-3 3.87"
          />
        ),
      },
      {
        href: "/logs",
        label: "Logs",
        // Mismo permiso que Troncales: la consola en vivo expone tráfico
        // SIP completo (números, cabeceras, credenciales de registro).
        permiso: PERMISOS.telefonia,
        icon: icon(
          <>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 17l6-6-6-6M12 19h8" />
          </>
        ),
      },
    ],
  },
  {
    title: "Automatización",
    items: [
      {
        href: "/voicebots",
        label: "Voizbots",
        permiso: PERMISOS.voizbotsVer,
        icon: icon(
          <>
            <rect x="4" y="8" width="16" height="12" rx="2" />
            <path strokeLinecap="round" d="M12 8V4m0 0a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM8 13v2M16 13v2" />
          </>
        ),
      },
      {
        href: "/ai-usage",
        label: "Consumo IA",
        permiso: PERMISOS.consumoIa,
        icon: icon(
          <>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 19V9m5 10V5m5 14v-7m5 7V8" />
          </>
        ),
      },
      {
        href: "/campaigns",
        label: "Campañas",
        permiso: PERMISOS.campanas,
        icon: icon(
          <>
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="5" />
            <circle cx="12" cy="12" r="1" />
          </>
        ),
      },
    ],
  },
  {
    title: "Sistema",
    items: [
      {
        href: "/empresas",
        label: "Empresas",
        permiso: PERMISOS.empresas,
        icon: icon(
          <>
            <rect x="3" y="9" width="18" height="12" rx="2" />
            <path strokeLinecap="round" d="M12 9V3m0 0a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM9 14h6M12 11v6" />
          </>
        ),
      },
      {
        href: "/users",
        label: "Usuarios",
        permiso: PERMISOS.usuarios,
        icon: icon(
          <>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"
            />
            <circle cx="9" cy="7" r="4" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
          </>
        ),
      },
      {
        href: "/settings",
        label: "Ajustes",
        permiso: PERMISOS.ajustes,
        icon: icon(
          <>
            <circle cx="12" cy="12" r="3" />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 004.6 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9c.14.31.22.65.24 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"
            />
          </>
        ),
      },
    ],
  },
];

const ALL_ITEMS = GROUPS.flatMap((g) => g.items);
const SIDEBAR_KEY = "nspbx-sidebar-collapsed";

// Qué módulo de la empresa habilita cada sección (modelo de packs — ver
// backend Tenant.modules). voicebot = el bot de IA; pbx = telefonía.
const MODULO_POR_SECCION: Record<string, string | null> = {
  "/softphone": "pbx",
  "/calls": "pbx",
  "/extensions": "pbx",
  "/trunks": "pbx",
  "/inbound-routes": "pbx",
  "/queues": "pbx",
  "/logs": "pbx",
  "/voicebots": "voicebot",
  "/ai-usage": "voicebot",
  "/campaigns": "voicebot",
  "/cobranza": "voicebot",
  "/appointments": "voicebot",
};

function SinAcceso({ rol }: { rol: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-warn-soft text-warn-text">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
          <rect x="4" y="11" width="16" height="10" rx="2" />
          <path strokeLinecap="round" d="M8 11V7a4 4 0 018 0v4" />
        </svg>
      </div>
      <h2 className="text-lg font-semibold tracking-tight text-fg">Esta sección no está en tu perfil</h2>
      <p className="max-w-sm text-sm leading-relaxed text-muted">
        Tu rol es <strong className="text-fg-soft">{rol}</strong> y no incluye esta pantalla. Si necesitas
        entrar, pídele a un administrador que revise tus permisos.
      </p>
      <Link
        href="/"
        className="press mt-2 rounded-xl border border-line px-3.5 py-1.5 text-sm font-medium text-fg-soft transition-colors hover:border-line-strong hover:bg-surface-2"
      >
        Volver al inicio
      </Link>
    </div>
  );
}

const ETIQUETA_ROL: Record<string, string> = {
  admin: "Administrador",
  supervisor: "Supervisor",
  coordinador: "Coordinador",
  asesor: "Asesor",
  plataforma: "Plataforma",
};

export default function SidebarLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <SoftphoneProvider>
        <IncomingCallBanner />
        <FloatingCallWidget />
        <AssistantWidget />
        <Marco>{children}</Marco>
      </SoftphoneProvider>
    </AuthProvider>
  );
}

function Marco({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { usuario, puede, tieneModulo, salir, cargando } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem(SIDEBAR_KEY) === "1");
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      } catch {
        // storage bloqueado: no persiste, pero la sesión funciona igual
      }
      return next;
    });
  };

  // El menú muestra solo lo que el rol puede abrir. No es la seguridad
  // —esa está en el backend, que responde 403 igual— sino no ofrecerle a
  // un asesor cinco pantallas que solo le van a dar error. Además se
  // ocultan las secciones del pack que la empresa no contrató (módulos).
  const grupos = GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => {
      if (i.permiso !== null && !puede(i.permiso)) return false;
      const mod = MODULO_POR_SECCION[i.href];
      if (mod && !tieneModulo(mod)) return false;
      return true;
    }),
  })).filter((g) => g.items.length > 0);

  // La ruta más específica que coincide gana, para que /voicebots/3/flow
  // marque "Voizbots" en el menú.
  const current = ALL_ITEMS.filter(
    (item) => pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href))
  ).sort((a, b) => b.href.length - a.href.length)[0];

  // El editor de flujo necesita toda la pantalla, sin el marco de la página.
  const fullBleed = pathname.includes("/flow");

  // El historial de llamadas son ocho columnas más un reproductor de audio:
  // no cabe en los 1280 px de `max-w-7xl` y quedaba con scroll horizontal
  // aun teniendo pantalla de sobra. Se le da el ancho que necesita.
  const ancha = pathname.startsWith("/calls");

  // La pantalla de entrada se dibuja sola, sin menú ni cabecera: no hay
  // sesión todavía y no habría nada que poner en ellos.
  //
  // /webcall también queda afuera: es la página del widget "hablar con un
  // agente" (ver app/webcall/page.tsx), la carga un <iframe> embebido en
  // el sitio de un cliente y la usa un visitante ANÓNIMO — nunca hay
  // sesión de panel ahí, así que ni el sidebar ni la verificación de
  // usuario de abajo tienen sentido (y sin esta excepción, `!usuario`
  // dejaría la página en blanco para siempre).
  if (pathname === "/login" || pathname === "/webcall") return <>{children}</>;
  if (cargando || !usuario) return null;

  // Escribir la dirección a mano no debe abrir una pantalla que el rol no
  // puede usar. El backend ya responde 403, pero sin esto la página se
  // dibuja igual y muestra su estado vacío ("No hay usuarios. Crea el
  // primero"), que hace pensar que no hay datos en vez de que no hay
  // permiso. Idem si la empresa no tiene el módulo.
  const sinAcceso =
    (current?.permiso != null && !puede(current.permiso)) ||
    (current != null &&
      MODULO_POR_SECCION[current.href] != null &&
      !tieneModulo(MODULO_POR_SECCION[current.href] as string));

  return (
    <div className="flex min-h-screen">
      {/* Línea de degradado superior: el borde de color que recorre toda la
          app y la saca de lo plano. */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-[60] h-[3px] bg-gradient-to-r from-brand via-accent to-info" />
      {mobileOpen && (
        <div
          className="animate-fade-soft fixed inset-0 z-30 bg-slate-950/50 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col border-r border-line bg-sidebar transition-[transform,width] duration-300 ease-out lg:static lg:translate-x-0 ${
          collapsed ? "w-[72px]" : "w-64"
        } ${mobileOpen ? "translate-x-0 shadow-[var(--shadow-3)]" : "-translate-x-full"}`}
      >
        <div className="flex h-16 items-center gap-2.5 px-4">
          <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 text-sm font-bold text-white shadow-[var(--shadow-brand)]">
            N
          </div>
          {!collapsed && (
            <div className="min-w-0 animate-fade-soft">
              <div className="truncate text-sm font-semibold tracking-tight text-fg">NSPBX</div>
              <div className="truncate text-[11px] text-faint">Central telefónica</div>
            </div>
          )}
        </div>

        <nav className="no-scrollbar flex-1 overflow-y-auto px-3 pb-4">
          {grupos.map((group) => (
            <div key={group.title} className="mb-4">
              {collapsed ? (
                <div className="mx-2 mb-2 border-t border-line" />
              ) : (
                <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-faint">
                  {group.title}
                </div>
              )}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = current?.href === item.href;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      title={collapsed ? item.label : undefined}
                      className={`group relative flex items-center gap-3 rounded-xl px-3 py-2 text-[13px] font-medium transition-all duration-200 ${
                        collapsed ? "justify-center" : ""
                      } ${
                        active
                          ? "bg-gradient-to-r from-brand-soft to-info-soft/60 text-brand-text"
                          : "text-muted hover:bg-surface-2 hover:text-fg"
                      }`}
                    >
                      {active && (
                        <span className="animate-fade-soft absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-brand" />
                      )}
                      <span
                        className={`transition-transform duration-200 group-hover:scale-110 ${
                          active ? "text-brand" : "text-faint group-hover:text-fg-soft"
                        }`}
                      >
                        {item.icon}
                      </span>
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Quién está usando el sistema. En un call center varias personas
            comparten equipo por turnos, así que tener el nombre y el rol
            siempre a la vista evita que alguien trabaje sin darse cuenta
            con la sesión del turno anterior. */}
        <div className="border-t border-line px-3 py-3">
          <div className={`flex items-center gap-2.5 ${collapsed ? "justify-center" : ""}`}>
            <div
              title={collapsed ? `${usuario.full_name} · ${ETIQUETA_ROL[usuario.role]}` : undefined}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[11px] font-semibold uppercase text-brand-text"
            >
              {usuario.full_name.slice(0, 2)}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1 animate-fade-soft">
                <div className="truncate text-[13px] font-medium text-fg">{usuario.full_name}</div>
                <div className="truncate text-[11px] text-faint">
                  {ETIQUETA_ROL[usuario.role] ?? usuario.role}
                  {usuario.extension_number && ` · ext. ${usuario.extension_number}`}
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={salir}
              title="Cerrar sesión"
              aria-label="Cerrar sesión"
              className={`press shrink-0 rounded-lg p-1.5 text-faint transition-colors hover:bg-surface-2 hover:text-danger ${
                collapsed ? "hidden" : ""
              }`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"
                />
              </svg>
            </button>
          </div>
        </div>

        <div
          className={`flex items-center gap-2 border-t border-line px-3 py-3 ${
            collapsed ? "flex-col" : "justify-between"
          }`}
        >
          {!collapsed && (
            <span className="truncate text-[10px] leading-tight text-faint">
              FreeSWITCH · FastAPI
              <br />
              PostgreSQL
            </span>
          )}
          <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expandir menú" : "Colapsar menú"}
            title={collapsed ? "Expandir menú" : "Colapsar menú"}
            className="press hidden h-8 w-8 items-center justify-center rounded-lg text-faint transition-colors hover:bg-surface-2 hover:text-fg lg:inline-flex"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path strokeLinecap="round" d="M9 4v16" />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d={collapsed ? "M13 10l2 2-2 2" : "M17 10l-2 2 2 2"}
              />
            </svg>
          </button>
        </div>
      </aside>

      <CommandPalette
        comandos={grupos.flatMap((g) => g.items.map((i) => ({ href: i.href, label: i.label, grupo: g.title, icon: i.icon })))}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/75 px-4 sm:px-6">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="press -ml-1 rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-fg lg:hidden"
            aria-label="Abrir menú"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
              <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <div className="flex min-w-0 items-center gap-2 text-sm">
            <span className="hidden text-muted sm:inline">NSPBX</span>
            <span className="hidden text-faint sm:inline">/</span>
            <span className="truncate font-semibold text-fg">{current?.label ?? "Panel"}</span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("nspbx:paleta"))}
              className="press hidden items-center gap-2 rounded-xl border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-faint transition-colors hover:border-line-strong hover:text-fg-soft sm:flex"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <circle cx="11" cy="11" r="7" />
                <path strokeLinecap="round" d="M20 20l-3.5-3.5" />
              </svg>
              Buscar
              <kbd className="rounded-md border border-line px-1.5 text-[10px]">Ctrl K</kbd>
            </button>
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 overflow-auto">
          <div
            key={pathname}
            className={
              fullBleed
                ? "animate-fade-soft h-full"
                : `animate-fade-up mx-auto p-4 sm:p-6 ${ancha ? "max-w-[1560px]" : "max-w-7xl"}`
            }
          >
            {sinAcceso ? <SinAcceso rol={ETIQUETA_ROL[usuario.role] ?? usuario.role} /> : children}
          </div>
        </main>
      </div>
    </div>
  );
}
