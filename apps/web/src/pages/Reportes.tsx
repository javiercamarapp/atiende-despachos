import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { portalApi, ReportCatalogItem, reportDownloadUrl } from "@/lib/api";

const Reportes = () => {
  const [reports, setReports] = useState<ReportCatalogItem[]>([]);
  const [invoiceCount, setInvoiceCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalApi
      .reports()
      .then((r) => {
        setReports(r.reports);
        setInvoiceCount(r.invoice_count);
      })
      .catch((e) => setError(e.message || "No se pudieron cargar los reportes."))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton className="h-64 rounded-2xl" />;
  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-[13px] text-destructive">{error}</CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted-foreground">
        Generados sobre {invoiceCount} factura{invoiceCount === 1 ? "" : "s"} de tu despacho.
      </p>
      <div className="grid md:grid-cols-2 gap-3">
        {reports.map((r) => (
          <Card key={r.id}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{r.nombre}</CardTitle>
            </CardHeader>
            <CardContent className="flex items-end justify-between gap-3">
              <p className="text-[13px] text-muted-foreground">{r.desc}</p>
              {/* Descarga real: enlace directo, no fetch — el endpoint ya
                  devuelve el archivo con Content-Disposition:attachment. */}
              <Button asChild size="sm" variant="outline" className="rounded-full shrink-0">
                <a href={reportDownloadUrl(r.id)}>
                  <Download className="w-3.5 h-3.5" />
                  Descargar
                </a>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default Reportes;
