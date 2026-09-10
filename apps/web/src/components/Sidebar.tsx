import {
  LayoutDashboard,
  FileText,
  ClipboardList,
  BarChart3,
  Settings,
  HelpCircle,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  UserRound,
  CreditCard,
  Bell,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ThemeSelector } from "@/components/ThemeSelector";
import { AtiendeMark, AtiendeWordmark } from "@/components/AtiendeLogo";
import { cn } from "@/lib/utils";

// Mismo patrón que AdminSidebar.tsx de atiende-restaurantes: sidebar +
// bloque de cuenta inferior estilo Likida (centro de ayuda/mi perfil/plan y
// facturación deshabilitados con "Pronto" — esas pantallas no existen en
// este backend tampoco —, Configuración SÍ enlaza a la página real).
const menuItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/cfdis", label: "CFDIs / Facturas", icon: FileText },
  { to: "/declaraciones", label: "Declaraciones", icon: ClipboardList },
  { to: "/reportes", label: "Reportes", icon: BarChart3 },
];

const CLAVE_COLAPSADO = "atiende-despachos-sidebar-colapsado";

interface SidebarProps {
  /** Identificador del tenant en sesión (tenant_id, un entero) — el backend
   * no expone hoy un endpoint con el email del usuario logueado
   * (_resolve_user lo resuelve server-side pero /portal/summary solo
   * devuelve tenant_id), así que se muestra el tenant real en vez de
   * inventar un email que no tenemos. */
  tenantLabel: number | null;
  onLogout: () => void;
}

export function Sidebar({ tenantLabel, onLogout }: SidebarProps) {
  const label = tenantLabel != null ? `Despacho #${tenantLabel}` : null;
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(CLAVE_COLAPSADO) === "1";
    } catch {
      return false;
    }
  });

  const toggle = () => {
    setCollapsed((v) => {
      const nuevo = !v;
      try {
        window.localStorage.setItem(CLAVE_COLAPSADO, nuevo ? "1" : "0");
      } catch {
        /* localStorage puede fallar en modo privado — no es crítico. */
      }
      return nuevo;
    });
  };

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col bg-card border border-border rounded-2xl sticky top-3 h-[calc(100vh-1.5rem)] overflow-hidden transition-all duration-300",
        collapsed ? "w-16" : "w-60",
      )}
    >
      <div className="h-14 px-3.5 flex items-center justify-between shrink-0">
        {!collapsed ? <AtiendeWordmark className="scale-90 origin-left" /> : <AtiendeMark className="h-6 w-auto" />}
        <button
          onClick={toggle}
          className="w-6 h-6 rounded-md border border-border/60 flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors shrink-0"
        >
          {collapsed ? <PanelLeftOpen className="w-3.5 h-3.5" strokeWidth={1.75} /> : <PanelLeftClose className="w-3.5 h-3.5" strokeWidth={1.75} />}
        </button>
      </div>

      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        {menuItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-[13px] transition-colors",
                isActive ? "bg-primary text-primary-foreground font-medium" : "text-muted-foreground hover:bg-muted",
              )
            }
          >
            <item.icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Bloque de cuenta — mismo patrón de dos capas que dashboard/chrome.tsx
          de Likida (y el mismo fix ya aplicado en atiende-restaurantes/
          citas-reservaciones/licitaciones/hoteles/rentas): zona hundida a
          todo lo ancho (bg-muted + sombra interior) y tarjeta de usuario
          SOBREPUESTA (margen negativo, fondo/borde/sombra propios). */}
      <div className="shrink-0 border-t border-border">
        {!collapsed && (
          <div className="bg-muted px-2 pt-2 pb-5 space-y-0.5 shadow-[inset_0_2px_5px_-2px_rgba(0,0,0,0.08)]">
            <button
              disabled
              className="mb-1 flex w-full items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-[13px] opacity-50 cursor-not-allowed"
            >
              <HelpCircle className="w-3.5 h-3.5 text-muted-foreground shrink-0" strokeWidth={1.75} />
              <span className="flex-1 flex items-center justify-between min-w-0 gap-2">
                <span className="truncate">Centro de ayuda</span>
                <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 shrink-0">Pronto</span>
              </span>
            </button>
            {/* Mismos 5 ítems y mismo orden que el bloque ABAJO real de
                Likida; activo = píldora sólida bg-primary. Solo
                "Configuración" tiene página real hoy en este repo. */}
            {[
              { label: "Notificaciones", icon: Bell },
              { label: "Mi perfil", icon: UserRound },
              { label: "Plan y facturación", icon: CreditCard },
            ].map((it) => (
              <button
                key={it.label}
                disabled
                className="w-full flex items-center gap-2.5 px-3 py-1.5 rounded-full text-[13px] text-muted-foreground/50 cursor-not-allowed"
              >
                <it.icon className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                <span className="flex-1 flex items-center justify-between min-w-0 gap-2">
                  <span className="truncate">{it.label}</span>
                  <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 shrink-0">Pronto</span>
                </span>
              </button>
            ))}
            <NavLink
              to="/configuracion"
              className={({ isActive }) =>
                cn(
                  "w-full flex items-center gap-2.5 px-3 py-1.5 rounded-full text-[13px] transition-colors",
                  isActive ? "bg-primary text-primary-foreground font-medium" : "text-muted-foreground hover:bg-background",
                )
              }
            >
              <Settings className="w-4 h-4 shrink-0" strokeWidth={1.75} />
              <span className="truncate">Configuración</span>
            </NavLink>
            <div className="pt-1.5 pb-0.5 flex justify-center">
              <ThemeSelector />
            </div>
          </div>
        )}

        <div className={cn("relative px-2 pb-2", collapsed ? "-mt-1" : "-mt-3.5")}>
          {!collapsed ? (
            <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-2 shadow-sm">
              <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-xs font-medium shrink-0">
                D
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] text-foreground truncate">{label || "Tu despacho"}</p>
                <p className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Cliente</p>
              </div>
              <button onClick={onLogout} className="text-destructive hover:opacity-70 shrink-0" aria-label="Cerrar sesión">
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <Button onClick={onLogout} variant="ghost" size="icon" className="w-full rounded-xl border border-border bg-card shadow-sm" aria-label="Cerrar sesión">
              <LogOut className="w-5 h-5" />
            </Button>
          )}
        </div>
      </div>
    </aside>
  );
}
