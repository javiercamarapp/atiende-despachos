// Shell de modal con el MISMO esqueleto literal de ModalClonarVoz.tsx —
// pedido real de Javier el 4-sep-2026 ("como el de clona tu voz, idéntico,
// misma forma, con ícono, esqueleto, todo — pero enfocado a cada recuadro")
// tras ver "Editar sucursal"/"Editar horario" con el esqueleto ANTERIOR
// (ícono centrado arriba, ModalFormularioElegante.tsx) y pedir el
// esqueleto real de ModalClonarVoz en su lugar: barra de gradiente, grid de
// dos columnas (riel izquierdo angosto con ícono/marca + título/subtítulo,
// columna derecha con el contenido real), botones al pie de la columna
// derecha (no un footer de ancho completo).
//
// ModalFormularioElegante.tsx (el esqueleto anterior, ícono centrado
// arriba) queda intacto para quien ya lo use — este es un shell hermano,
// no un reemplazo forzado, para reusar el mismo <CampoFormulario> en
// ambos.
import { ReactNode } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AtiendeMark } from "@/components/AtiendeLogo";
import { LucideIcon, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ModalFormularioLateralProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * @deprecated Todos los popups usan el logo (AtiendeMark) en el riel,
   * nunca un ícono por-recuadro — pedido real de Javier el 4-sep-2026
   * ("ponle el icono del logo como el de clonar voz a todos los pops ups
   * unificalos quitale eso"). Se ignora si se pasa; queda en la interfaz
   * solo para no romper los call sites existentes.
   */
  icono?: LucideIcon;
  /** Título en el riel izquierdo (font-display, bold) — "Clonación instantánea de voz" en el original. */
  titulo: string;
  /** Texto secundario opcional bajo el título, en el riel izquierdo. */
  subtitulo?: string;
  /**
   * Lista de pasos opcional (solo para modales multi-paso reales, como
   * ModalClonarVoz) — puntos + etiqueta, el activo resaltado. Omitir en
   * formularios de un solo paso (la mayoría): el riel se queda solo con
   * ícono + título/subtítulo, sin inventar pasos que no existen.
   */
  pasos?: { id: string; etiqueta: string }[];
  pasoActivo?: string;
  /** Contenido de la columna derecha — normalmente <CampoFormulario> o layout propio (ej. formulario + mapa). */
  children: ReactNode;
  /**
   * Botones al pie de la columna derecha (fila justify-between, como
   * "Atrás"/"Siguiente" en ModalClonarVoz). Si se omite, se arma un botón
   * primario rounded-full alineado a la derecha con onGuardar/guardando.
   */
  footer?: ReactNode;
  onGuardar?: () => void;
  guardando?: boolean;
  textoBotonGuardar?: string;
  guardarDeshabilitado?: boolean;
  /** Ancho del modal. @default "max-w-5xl" (igual que ModalClonarVoz) */
  anchoClase?: string;
  /** Ancho fijo del riel izquierdo. @default "220px" (igual que ModalClonarVoz) */
  anchoRiel?: string;
  /** Alto mínimo del contenido, para que no "salte" al cambiar de contenido interno. Omitir si el contenido es fijo (la mayoría de los formularios de un solo paso). */
  altoMinimoClase?: string;
  bloquearCierre?: boolean;
}

export function ModalFormularioLateral({
  open,
  onOpenChange,
  titulo,
  subtitulo,
  pasos,
  pasoActivo,
  children,
  footer,
  onGuardar,
  guardando = false,
  textoBotonGuardar = "Guardar cambios",
  guardarDeshabilitado = false,
  anchoClase = "max-w-5xl",
  anchoRiel = "220px",
  altoMinimoClase,
  bloquearCierre = false,
}: ModalFormularioLateralProps) {
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onOpenChange(false); }}>
      <DialogContent
        hideDefaultClose
        className={cn(anchoClase, "p-0 gap-0 overflow-hidden")}
        onInteractOutside={bloquearCierre ? (e) => e.preventDefault() : undefined}
        onEscapeKeyDown={bloquearCierre ? (e) => e.preventDefault() : undefined}
      >
        <div className="h-1 bg-gradient-to-r from-primary to-secondary" />

        {!bloquearCierre && (
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Cerrar"
            className="absolute right-3 top-4 z-10 w-7 h-7 rounded-full flex items-center justify-center text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors"
          >
            <X className="w-4 h-4" strokeWidth={1.75} />
          </button>
        )}

        <div className={cn("grid", altoMinimoClase)} style={{ gridTemplateColumns: `${anchoRiel} 1fr` }}>
          {/* Riel izquierdo: marca (siempre el logo, nunca un ícono por-recuadro) + título/subtítulo (+ pasos si aplica) */}
          <div className="border-r border-border p-6 flex flex-col gap-6 bg-muted/30">
            <AtiendeMark className="h-7 w-auto" />
            <div>
              <p className="font-display text-base font-semibold text-foreground mb-1">{titulo}</p>
              {subtitulo && <p className="text-[13px] text-muted-foreground leading-snug">{subtitulo}</p>}

              {pasos && pasos.length > 0 && (
                <div className="space-y-3 mt-4">
                  {pasos.map((p) => {
                    const activo = p.id === pasoActivo;
                    const indiceActivo = pasos.findIndex((x) => x.id === pasoActivo);
                    const completado = indiceActivo > pasos.findIndex((x) => x.id === p.id);
                    return (
                      <div key={p.id} className="flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${activo ? "bg-primary" : completado ? "bg-primary/50" : "bg-border"}`} />
                        <span className={`text-[13px] ${activo ? "font-medium text-foreground" : "text-muted-foreground"}`}>{p.etiqueta}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Columna derecha: contenido real + botones al pie */}
          <div className="p-6 flex flex-col">
            <div className="flex-1 overflow-y-auto">{children}</div>
            <div className="flex items-center justify-end gap-2 mt-auto pt-5">
              {footer ?? (
                <Button
                  className="rounded-full px-6"
                  onClick={onGuardar}
                  disabled={guardando || guardarDeshabilitado}
                >
                  {guardando ? "Guardando…" : textoBotonGuardar}
                </Button>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
