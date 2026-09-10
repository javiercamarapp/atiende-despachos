import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { portalApi, InvoiceDetail as InvoiceDetailType } from "@/lib/api";

function money(v: number) {
  return v.toLocaleString("es-MX", { style: "currency", currency: "MXN" });
}

function Campo({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-[14px] text-foreground mt-0.5">{value ?? "—"}</dd>
    </div>
  );
}

const InvoiceDetail = () => {
  const { id } = useParams<{ id: string }>();
  const [inv, setInv] = useState<InvoiceDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    portalApi
      .invoice(Number(id))
      .then(setInv)
      .catch((e) => setError(e.message || "No se pudo cargar la factura."))
      .finally(() => setLoading(false));
  }, [id]);

  return (
    <div className="space-y-4">
      <Link to="/cfdis" className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" /> Volver a facturas
      </Link>

      {loading && <Skeleton className="h-80 rounded-2xl" />}

      {error && (
        <Card>
          <CardContent className="p-6 text-[13px] text-destructive">{error}</CardContent>
        </Card>
      )}

      {inv && !loading && (
        <>
          <Card>
            <CardContent className="p-4 flex items-center justify-between flex-wrap gap-2">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Folio fiscal</p>
                <p className="text-base font-semibold text-foreground">{inv.folio_fiscal || "—"}</p>
              </div>
              <Badge variant={inv.estatus === "procesado" ? "secondary" : "destructive"}>{inv.estatus}</Badge>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4">
              <dl className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <Campo label="Archivo" value={inv.archivo} />
                <Campo label="Fecha" value={inv.fecha} />
                <Campo label="Tipo" value={inv.tipo} />
                <Campo label="Serie / Folio" value={`${inv.serie || ""} ${inv.folio || ""}`.trim() || "—"} />
                <Campo label="Emisor" value={`${inv.emisor_nombre || ""} · ${inv.emisor_rfc || "—"}`} />
                <Campo label="Receptor (RFC)" value={inv.receptor_rfc} />
                <Campo label="Subtotal" value={money(inv.subtotal)} />
                <Campo label="IVA" value={money(inv.iva)} />
                <Campo label="Total" value={<b>{money(inv.total)}</b>} />
                <Campo label="Moneda" value={inv.moneda} />
                <Campo label="Categoría" value={inv.categoria} />
                <Campo label="Confianza" value={inv.confianza != null ? `${Math.round(inv.confianza * 100)}%` : "—"} />
                <Campo label="Estatus ERP" value={inv.erp_status} />
                <Campo label="Procesado en" value={inv.procesado_en} />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 space-y-3">
              <div>
                <h2 className="text-[13px] font-semibold text-foreground">Razón de clasificación</h2>
                <p className="text-[13px] text-muted-foreground mt-1">{inv.razon_clasificacion || "Sin justificación registrada."}</p>
              </div>
              {inv.issues && (
                <div>
                  <h2 className="text-[13px] font-semibold text-foreground">Problemas detectados</h2>
                  <p className="text-[13px] text-muted-foreground mt-1">{inv.issues}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
};

export default InvoiceDetail;
