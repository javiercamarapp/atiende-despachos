// Recreación vectorial del logo real (figura corriendo + líneas de
// movimiento + wordmark "atiende", dos tonos de azul). No tengo el archivo
// original — esto es una reconstrucción fiel al mismo mark, no el asset.
export function AtiendeMark({ className = "h-7 w-auto", animado = false }: { className?: string; animado?: boolean }) {
  return (
    <svg viewBox="0 0 40 32" className={`${className} ${animado ? "atiende-glifo-animado" : ""}`} fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect className="atiende-linea atiende-linea-1" x="0" y="4" width="13" height="4" rx="2" fill="#7DD3FC" />
      <rect className="atiende-linea atiende-linea-2" x="4" y="12" width="13" height="4" rx="2" fill="#7DD3FC" />
      <rect className="atiende-linea atiende-linea-3" x="0" y="20" width="13" height="4" rx="2" fill="#7DD3FC" />
      <circle cx="26" cy="6" r="5" fill="#38BDF8" />
      <path
        d="M14 32 L20 20 Q22 16 27 16 L31 16 Q34 16 36 13 L38 10"
        stroke="#1D4ED8"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

export function AtiendeWordmark({ className = "", markClassName = "", animado = false }: { className?: string; markClassName?: string; animado?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <AtiendeMark className={markClassName || "h-7 w-auto"} animado={animado} />
      <span className="font-display text-2xl font-bold tracking-tight" style={{ color: "#1D4ED8" }}>
        atiende
      </span>
    </span>
  );
}
