import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { AUTH_EVENT, portalApi } from "@/lib/api";

// La sesión vive en una cookie httpOnly — el cliente JS no puede leerla.
// "¿hay sesión?" se responde probando un endpoint real (/portal/summary,
// que ya se necesita para el dashboard) en vez de inventar un estado que
// después hay que sincronizar a mano.
type EstadoAuth = "cargando" | "autenticado" | "anonimo";

interface AuthContextValue {
  estado: EstadoAuth;
  tenantId: number | null;
  login: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  marcarAutenticado: (tenantId: number) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<EstadoAuth>("cargando");
  const [tenantId, setTenantId] = useState<number | null>(null);

  const verificar = useCallback(async () => {
    try {
      const summary = await portalApi.summary();
      setTenantId(summary.tenant_id);
      setEstado("autenticado");
    } catch {
      setEstado("anonimo");
      setTenantId(null);
    }
  }, []);

  useEffect(() => {
    verificar();
    const onUnauthorized = () => {
      setEstado("anonimo");
      setTenantId(null);
    };
    window.addEventListener(AUTH_EVENT, onUnauthorized);
    return () => window.removeEventListener(AUTH_EVENT, onUnauthorized);
  }, [verificar]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await portalApi.login(email, password);
    if (res.ok) {
      await verificar();
    }
    return res;
  }, [verificar]);

  const logout = useCallback(async () => {
    try {
      await portalApi.logout();
    } finally {
      setEstado("anonimo");
      setTenantId(null);
    }
  }, []);

  const marcarAutenticado = useCallback((tid: number) => {
    setTenantId(tid);
    setEstado("autenticado");
  }, []);

  return (
    <AuthContext.Provider value={{ estado, tenantId, login, logout, marcarAutenticado }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
