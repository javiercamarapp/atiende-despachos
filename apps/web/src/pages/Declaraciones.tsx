import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { portalApi, Declaracion } from "@/lib/api";

function money(v: number | null) {
  if (v == null) return "—";
  return v.toLocaleString("es-MX", { style: "currency", currency: "MXN" });
}

const ESTADOS_CERRADOS = ["enviado", "timbrado_final", "entregado"];

const Declaraciones = () => {
  const [items, setItems] = useState<Declaracion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalApi
      .declaraciones()
      .then((r) => setItems(r.declaraciones))
      .catch((e) => setError(e.message || "No se pudieron cargar las declaraciones."))
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
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Periodo</TableHead>
              <TableHead>RFC</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="text-right">Monto</TableHead>
              <TableHead>Actualizado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-[13px] text-muted-foreground py-8">
                  Sin datos todavía.
                </TableCell>
              </TableRow>
            ) : (
              items.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>{d.periodo || "—"}</TableCell>
                  <TableCell className="font-mono text-[12px]">{d.rfc || "—"}</TableCell>
                  <TableCell>{d.tipo || "—"}</TableCell>
                  <TableCell>
                    <Badge variant={ESTADOS_CERRADOS.includes(d.estado) ? "secondary" : "outline"}>{d.estado}</Badge>
                  </TableCell>
                  <TableCell className="text-right">{money(d.monto)}</TableCell>
                  <TableCell>{d.actualizado || "—"}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
};

export default Declaraciones;
