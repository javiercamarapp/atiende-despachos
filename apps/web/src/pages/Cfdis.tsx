import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { portalApi, Cfdi } from "@/lib/api";

function money(v: number) {
  return v.toLocaleString("es-MX", { style: "currency", currency: "MXN" });
}

function estadoBadge(estatus: string) {
  const variant = estatus === "anomalia" ? "destructive" : estatus === "invalida" ? "destructive" : estatus === "procesado" ? "secondary" : "outline";
  return <Badge variant={variant}>{estatus}</Badge>;
}

const Cfdis = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [cfdis, setCfdis] = useState<Cfdi[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [fechaDesde, setFechaDesde] = useState(searchParams.get("fecha_desde") || "");
  const [fechaHasta, setFechaHasta] = useState(searchParams.get("fecha_hasta") || "");
  const [estatus, setEstatus] = useState(searchParams.get("estatus") || "");
  const [montoMin, setMontoMin] = useState(searchParams.get("monto_min") || "");
  const [montoMax, setMontoMax] = useState(searchParams.get("monto_max") || "");

  const cargar = () => {
    setLoading(true);
    setError(null);
    portalApi
      .cfdis({
        fecha_desde: fechaDesde || undefined,
        fecha_hasta: fechaHasta || undefined,
        estatus: estatus || undefined,
        monto_min: montoMin || undefined,
        monto_max: montoMax || undefined,
      })
      .then((r) => setCfdis(r.cfdis))
      .catch((e) => setError(e.message || "No se pudieron cargar los CFDIs."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const aplicarFiltros = (e: React.FormEvent) => {
    e.preventDefault();
    const params: Record<string, string> = {};
    if (fechaDesde) params.fecha_desde = fechaDesde;
    if (fechaHasta) params.fecha_hasta = fechaHasta;
    if (estatus) params.estatus = estatus;
    if (montoMin) params.monto_min = montoMin;
    if (montoMax) params.monto_max = montoMax;
    setSearchParams(params);
    cargar();
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4">
          <form onSubmit={aplicarFiltros} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="f-desde" className="text-[11px]">Desde</Label>
              <Input id="f-desde" type="date" value={fechaDesde} onChange={(e) => setFechaDesde(e.target.value)} className="h-9 w-[150px]" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="f-hasta" className="text-[11px]">Hasta</Label>
              <Input id="f-hasta" type="date" value={fechaHasta} onChange={(e) => setFechaHasta(e.target.value)} className="h-9 w-[150px]" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="f-estatus" className="text-[11px]">Estatus</Label>
              <Input id="f-estatus" placeholder="procesado, anomalia…" value={estatus} onChange={(e) => setEstatus(e.target.value)} className="h-9 w-[160px]" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="f-min" className="text-[11px]">Monto mín.</Label>
              <Input id="f-min" type="number" value={montoMin} onChange={(e) => setMontoMin(e.target.value)} className="h-9 w-[110px]" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="f-max" className="text-[11px]">Monto máx.</Label>
              <Input id="f-max" type="number" value={montoMax} onChange={(e) => setMontoMax(e.target.value)} className="h-9 w-[110px]" />
            </div>
            <Button type="submit" size="sm" className="h-9 rounded-full">Filtrar</Button>
          </form>
        </CardContent>
      </Card>

      {error && (
        <Card>
          <CardContent className="p-4 text-[13px] text-destructive">{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <Skeleton className="h-64 rounded-2xl" />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Folio fiscal</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Emisor</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Estatus</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cfdis.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-[13px] text-muted-foreground py-8">
                      Sin datos todavía.
                    </TableCell>
                  </TableRow>
                ) : (
                  cfdis.map((c) => (
                    <TableRow
                      key={c.id}
                      className="cursor-pointer"
                      onClick={() => navigate(`/cfdis/${c.id}`)}
                    >
                      <TableCell className="font-mono text-[12px]">{c.folio_fiscal || "—"}</TableCell>
                      <TableCell>{c.fecha || "—"}</TableCell>
                      <TableCell className="truncate max-w-[220px]">{c.emisor_nombre || c.emisor_rfc || "—"}</TableCell>
                      <TableCell className="text-right">{money(c.total)}</TableCell>
                      <TableCell>{estadoBadge(c.estatus)}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default Cfdis;
