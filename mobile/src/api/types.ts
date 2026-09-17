// Mismas formas que backend/app/schemas/schemas.py — solo los campos que
// la app móvil usa.

export interface UsuarioOut {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: string;
  extension_id: number | null;
  extension_number: string | null;
}

export interface SesionOut {
  token: string;
  expira_en: number;
  usuario: UsuarioOut;
  permisos: string[];
  modulos: string[];
  refresh_token: string | null;
}

export interface MiEntorno {
  extension: {
    id: number;
    number: string;
    password: string;
    caller_id_name: string | null;
    enabled: boolean;
    dnd: boolean;
  } | null;
  ice_servers: { urls: string[] | string; username?: string; credential?: string }[];
  fs_domain: string | null;
  sip_ws_url: string | null;
  sip_server_ip: string | null;
  sip_server_port: number | null;
}

export interface CallStats {
  total: number;
  answered: number;
  no_answer: number;
  busy: number;
  failed: number;
  talk_minutes: number;
}

export interface CallLogOut {
  id: number;
  direction: string;
  caller_number: string | null;
  caller_name: string | null;
  callee_number: string | null;
  status: string;
  duration: number;
  billsec: number;
  started_at: string | null;
  recording_path: string | null;
}

export interface AiUsageSummary {
  calls: number;
  resolved: number;
  containment_rate: number;
  turns: number;
  cost_usd: number;
  cost_per_call: number;
  cost_per_resolved: number;
  avg_turns: number;
  avg_duration: number;
  cost_per_minute: number;
}
