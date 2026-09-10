import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, ClipboardList, AlertTriangle, Coins, Clock, ShieldCheck, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { portalApi, Summary, Metrics, Alerta } from "@/lib/api";

function money(v: number) {
  return v.toLocaleString("es-MX", { style: "currency", currency: "MXN", maximumFractionDigits: 0 });
}

function StatCard({ icon: Icon, label, value, hint }: { icon: typeof FileText; label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-4 flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Icon className="w-4.5 h-4.5 text-primary" strokeWidth={1.75} />
        </div>
        <div className="min-w-0">
          <p className="text-[12px] text-muted-foreground">{label}</p>
          <p className="text-xl font-semibold text-foreground truncate">{value}</p>
          {hint && <p className="text-[11px] text-muted-foreground mt-0.5">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

const Dashboard = () => {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [alertas, setAlertas] = useState<Alerta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    Promise.all([portalApi.summary(), portalApi.metrics(), portalApi.alertas(10)])
      .then(([s, m, a]) => {
        if (cancelado) return;
        setSummary(s);
        setMetrics(m);
        setAlertas(a.alertas);
      })
      .catch((e) => {
        if (!cancelado) setError(e.message || "No se pudo cargar el dashboard.");
      })
      .finally(() => {
        if (!cancelado) setLoading(false);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-[13px] text-destructive">{error}</CardContent>
      </Card>
    );
  }

  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={FileText} label="CFDIs procesados" value={String(summary?.cfdis_procesados ?? 0)} hint={`${summary?.cfdis_total ?? 0} en total`} />
        <StatCard icon={Clock} label="CFDIs pendientes" value={String(summary?.cfdis_pendientes ?? 0)} />
        <StatCard icon={AlertTriangle} label="Anomalías" value={String(summary?.cfdis_anomalias ?? 0)} />
        <StatCard icon={Coins} label="Monto total" value={summary ? money(summary.monto_total) : "—"} hint={summary ? `IVA ${money(summary.iva_total)}` : undefined} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={ClipboardList} label="Declaraciones pendientes" value={String(summary?.declaraciones_pendientes ?? 0)} hint={`${summary?.declaraciones_total ?? 0} en total`} />
        <StatCard icon={ShieldCheck} label="Alertas activas" value={String(summary?.alertas_activas ?? 0)} />
        <StatCard icon={Clock} label="Horas ahorradas" value={metrics ? metrics.horas_ahorradas.toLocaleString("es-MX") : "—"} />
        <StatCard icon={TrendingUp} label="ROI estimado" value={metrics ? `${(metrics.roi * 100).toFixed(0)}%` : "—"} hint={metrics ? `Ahorro ${money(metrics.ahorro_mano_obra)}` : undefined} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            Alertas recientes
            <Link to="/cfdis" className="text-[12px] font-normal text-primary hover:underline">
              Ver CFDIs
            </Link>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {alertas.length === 0 ? (
            <p className="px-4 pb-4 text-[13px] text-muted-foreground">Sin alertas registradas todavía.</p>
          ) : (
            <ul className="divide-y divide-border">
              {alertas.map((a) => (
                <li key={a.id} className="px-4 py-3 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[13px] text-foreground truncate">{a.tema || "Alerta"}</p>
                    {a.detalle && <p className="text-[12px] text-muted-foreground truncate">{a.detalle}</p>}
                  </div>
                  <Badge variant={a.resuelta ? "secondary" : a.severidad === "warning" ? "destructive" : "outline"} className="shrink-0">
                    {a.resuelta ? "Resuelta" : a.severidad === "warning" ? "Atención" : "Info"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Dashboard;
