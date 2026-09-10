import { Link } from "react-router-dom";

const NotFound = () => (
  <main className="min-h-screen flex flex-col items-center justify-center gap-3 text-center px-6">
    <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">404</p>
    <h1 className="text-xl font-semibold text-foreground">Página no encontrada</h1>
    <Link to="/" className="text-[13px] text-primary hover:underline">
      Volver al panel
    </Link>
  </main>
);

export default NotFound;
