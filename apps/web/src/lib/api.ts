// Cliente HTTP del portal. Todas las llamadas van con credentials:"include"
// (cookie de sesión httpOnly `portal_session`, seteada por
// POST /portal/api/login). Base URL configurable por VITE_API_URL — vacío
// (default) usa same-origin, correcto tanto en dev (vía el proxy de Vite a
// /portal, ver vite.config.ts) como en prod si el backend sirve este build
// como estáticos.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) || "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Se dispara cuando una llamada regresa 401 — el shell de la app escucha
 * este evento para mandar a login sin que cada página tenga que manejarlo. */
export const AUTH_EVENT = "despachos:unauthorized";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    ...init,
  });

  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EVENT));
    throw new ApiError("Sesión expirada.", 401);
  }

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const detail =
      (typeof body === "object" && body !== null &&
        ((body as Record<string, unknown>).error || (body as Record<string, unknown>).detail)) ||
      `Error ${res.status}`;
    throw new ApiError(String(detail), res.status);
  }

  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", body: data !== undefined ? JSON.stringify(data) : undefined }),
  put: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PUT", body: data !== undefined ? JSON.stringify(data) : undefined }),
};

// ---------------------------------------------------------------------------
// Tipos de datos reales devueltos por b2b_ai/portal/routes.py — un reflejo
// literal de los dicts que la API ya construye, no un modelo aspiracional.
// ---------------------------------------------------------------------------
export interface Summary {
  tenant_id: number;
  cfdis_procesados: number;
  cfdis_pendientes: number;
  cfdis_anomalias: number;
  cfdis_total: number;
  monto_total: number;
  iva_total: number;
  declaraciones_pendientes: number;
  declaraciones_total: number;
  alertas_activas: number;
  ultima_actividad: string | null;
}

export interface Cfdi {
  id: number;
  folio_fiscal: string | null;
  fecha: string | null;
  tipo: string | null;
  emisor_rfc: string | null;
  emisor_nombre: string | null;
  categoria: string | null;
  confianza: number | null;
  total: number;
  iva: number;
  moneda: string;
  valido: boolean;
  estatus: string;
}

export interface CfdisResponse {
  tenant_id: number;
  count: number;
  cfdis: Cfdi[];
}

export interface InvoiceDetail {
  id: number;
  archivo: string | null;
  folio_fiscal: string | null;
  fecha: string | null;
  tipo: string | null;
  serie: string | null;
  folio: string | null;
  emisor_rfc: string | null;
  emisor_nombre: string | null;
  receptor_rfc: string | null;
  subtotal: number;
  iva: number;
  total: number;
  moneda: string;
  categoria: string | null;
  confianza: number | null;
  descripcion: string | null;
  erp_status: string | null;
  procesado_en: string | null;
  razon_clasificacion: string | null;
  issues: string | null;
  valido: boolean;
  requires_human_review: boolean;
  status: string | null;
  estatus: string;
}

export interface Declaracion {
  id: number;
  periodo: string | null;
  rfc: string | null;
  estado: string;
  tipo: string | null;
  monto: number | null;
  actualizado: string | null;
}

export interface DeclaracionesResponse {
  tenant_id: number;
  count: number;
  pendientes: number;
  declaraciones: Declaracion[];
}

export interface Alerta {
  id: string;
  tipo: string;
  tema: string | null;
  detalle: string | null;
  fecha: string | null;
  severidad: string;
  resuelta: boolean;
}

export interface AlertasResponse {
  tenant_id: number;
  count: number;
  activas: number;
  resueltas: number;
  alertas: Alerta[];
}

export interface Metrics {
  tenant_id: number;
  cfdis_procesados: number;
  horas_ahorradas: number;
  errores_evitados: number;
  ahorro_mano_obra: number;
  inversion_estimada: number;
  roi: number;
  tasa_error_manual_referencia: number;
}

export interface ReportCatalogItem {
  id: string;
  nombre: string;
  desc: string;
}

export interface ReportsResponse {
  reports: ReportCatalogItem[];
  invoice_count: number;
}

export interface TenantSettings {
  rfc: string;
  erp_type: string;
  plantilla_contable: string;
  notif_channel: string;
  notif_recipient: string;
}

export const portalApi = {
  login: (email: string, password: string) =>
    api.post<{ ok: boolean; error?: string }>("/portal/api/login", { email, password }),
  logout: () => api.post<{ ok: boolean }>("/portal/api/logout"),
  summary: () => api.get<Summary>("/portal/summary"),
  metrics: () => api.get<Metrics>("/portal/metrics"),
  cfdis: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return api.get<CfdisResponse>(`/portal/cfdis${suffix}`);
  },
  invoice: (id: number) => api.get<InvoiceDetail>(`/portal/api/invoices/${id}`),
  declaraciones: () => api.get<DeclaracionesResponse>("/portal/declaraciones"),
  alertas: (limit = 50) => api.get<AlertasResponse>(`/portal/alertas?limit=${limit}`),
  reports: () => api.get<ReportsResponse>("/portal/api/reports"),
  settings: () => api.get<{ tenant_id: number; settings: TenantSettings }>("/portal/api/settings"),
  updateSettings: (data: Partial<TenantSettings>) =>
    api.put<{ ok: boolean; tenant_id: number; updated: string[] }>("/portal/settings", data),
};

export function reportDownloadUrl(reportId: string) {
  return `${API_BASE}/portal/reports/${reportId}/download`;
}
