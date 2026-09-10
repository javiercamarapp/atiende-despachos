import { ReactNode, useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { MessageCircle, Bell } from "lucide-react";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import { Sidebar } from "@/components/Sidebar";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/hooks/use-toast";
import { portalApi } from "@/lib/api";

const TITULOS: Record<string, string> = {
  "/": "Dashboard",
  "/cfdis": "CFDIs / Facturas",
  "/declaraciones": "Declaraciones",
  "/reportes": "Reportes",
  "/configuracion": "Configuración",
};

export function Layout({ children }: { children: ReactNode }) {
  const { tenantId, logout } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [alertasActivas, setAlertasActivas] = useState(0);

  useEffect(() => {
    let cancelado = false;
    portalApi
      .alertas()
      .then((r) => {
        if (!cancelado) setAlertasActivas(r.activas);
      })
      .catch(() => {
        /* si falla, la campana se queda en 0 — no es crítico para el layout */
      });
    return () => {
      cancelado = true;
    };
  }, [location.pathname]);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const titulo = TITULOS[location.pathname] || "Panel";

  return (
    <div className="min-h-screen bg-background flex gap-3 p-3 max-w-[1400px] mx-auto">
      <Sidebar tenantLabel={tenantId} onLogout={handleLogout} />

      <main className="flex-1 min-w-0 space-y-4 pb-8">
        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <h1 className="font-display text-xl font-semibold text-foreground">{titulo}</h1>

          <div className="flex items-center gap-2">
            {location.pathname === "/" && (
              <>
                {/* Mismo patrón honesto que citas-reservaciones/atiende-restaurantes:
                    "Chatea con tus datos" no está conectada a datos reales todavía —
                    el botón lo dice en vez de fingir una respuesta de IA. */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    toast({
                      title: "Chatea con tus datos",
                      description: "Esta función todavía no está conectada a tus datos reales — llega en una próxima actualización.",
                    })
                  }
                  className="h-8 rounded-full text-[13px] shrink-0"
                >
                  <MessageCircle className="w-3.5 h-3.5" />
                  Chatea con tus datos
                </Button>
                <button
                  onClick={() => navigate("/cfdis")}
                  aria-label={`Alertas activas: ${alertasActivas}`}
                  className="relative w-8 h-8 rounded-full border border-border flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors shrink-0"
                >
                  <Bell className="w-4 h-4" strokeWidth={1.75} />
                  {alertasActivas > 0 && (
                    <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-mono font-medium leading-4 text-center">
                      {alertasActivas > 999 ? "999+" : alertasActivas}
                    </span>
                  )}
                </button>
                <span className="font-mono text-xs text-muted-foreground border border-border rounded-full px-3 py-1.5 shrink-0">
                  {format(new Date(), "d MMM yyyy", { locale: es })}
                </span>
              </>
            )}
          </div>
        </div>

        {children}
      </main>
    </div>
  );
}
