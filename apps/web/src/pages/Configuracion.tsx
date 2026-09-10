import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { portalApi, TenantSettings } from "@/lib/api";

const DEFAULTS: TenantSettings = {
  rfc: "",
  erp_type: "contpaqi",
  plantilla_contable: "SAT",
  notif_channel: "email",
  notif_recipient: "",
};

const Configuracion = () => {
  const { toast } = useToast();
  const [form, setForm] = useState<TenantSettings>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalApi
      .settings()
      .then((r) => setForm(r.settings))
      .catch((e) => setError(e.message || "No se pudo cargar la configuración."))
      .finally(() => setLoading(false));
  }, []);

  const campo = (key: keyof TenantSettings) => ({
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value })),
  });

  const guardar = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await portalApi.updateSettings(form);
      toast({ title: "Configuración guardada", description: res.updated.length ? `Actualizado: ${res.updated.join(", ")}` : "Sin cambios." });
    } catch (err) {
      toast({
        title: "No se pudo guardar",
        description: err instanceof Error ? err.message : "Error desconocido.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle className="text-base">Configuración del despacho</CardTitle>
      </CardHeader>
      <CardContent>
        {error && <p className="text-[13px] text-destructive mb-4">{error}</p>}
        <form onSubmit={guardar} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="rfc">RFC</Label>
            <Input id="rfc" {...campo("rfc")} placeholder="XAXX010101000" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="erp_type">ERP</Label>
            <Input id="erp_type" {...campo("erp_type")} placeholder="contpaqi" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="plantilla_contable">Plantilla contable</Label>
            <Input id="plantilla_contable" {...campo("plantilla_contable")} placeholder="SAT" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="notif_channel">Canal de notificaciones</Label>
            <Input id="notif_channel" {...campo("notif_channel")} placeholder="email" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="notif_recipient">Destinatario de notificaciones</Label>
            <Input id="notif_recipient" {...campo("notif_recipient")} placeholder="contador@despacho.mx" />
          </div>
          <Button type="submit" disabled={saving} className="rounded-full">
            {saving ? "Guardando…" : "Guardar cambios"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

export default Configuracion;
