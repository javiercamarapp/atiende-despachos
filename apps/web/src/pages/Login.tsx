import { useState } from "react";
import { Navigate } from "react-router-dom";
import { AtiendeMark, AtiendeWordmark } from "@/components/AtiendeLogo";
import { useAuth } from "@/hooks/useAuth";
import { useToast } from "@/hooks/use-toast";
import "./login.css";

// Login split-screen, mismo patrón exacto que AdminLogin.tsx de
// atiende-restaurantes (login.css: .login-lamina/.login-velo/
// .login-foto-marca + kicker/serif/píldoras) — la diferencia real es la
// autenticación: este backend (FastAPI) usa email+password contra
// POST /portal/api/login, no magic-link de Supabase.
const Login = () => {
  const { estado, login } = useAuth();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  if (estado === "autenticado") {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    setLoading(true);
    try {
      const res = await login(email, password);
      if (!res.ok) {
        toast({
          title: "No se pudo iniciar sesión",
          description: res.error || "Credenciales inválidas.",
          variant: "destructive",
        });
      }
    } catch {
      toast({
        title: "No se pudo iniciar sesión",
        description: "Ocurrió un error de red. Intenta de nuevo.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login min-h-screen lg:grid lg:grid-cols-2">
      <section className="flex min-h-screen flex-col px-6 py-7 sm:px-10 lg:px-14 lg:py-10">
        <div className="mx-auto flex w-full max-w-[392px] flex-1 flex-col">
          <header className="login-entra flex items-center">
            <AtiendeWordmark />
          </header>

          <div className="flex flex-1 items-center py-12">
            <div className="w-full">
              <p className="login-entra login-kicker" style={{ animationDelay: "40ms" }}>
                Acceso al portal
              </p>
              <h1
                className="login-entra login-serif mt-5 text-[38px] sm:text-[44px] text-foreground"
                style={{ animationDelay: "90ms" }}
              >
                Bienvenido a atiende
              </h1>
              <p
                className="login-entra mt-4 text-[15px] leading-[1.6] text-muted-foreground"
                style={{ animationDelay: "140ms" }}
              >
                El portal de tu despacho contable: CFDIs, declaraciones y reportes.
              </p>

              <div className="login-entra mt-9 h-px bg-border" style={{ animationDelay: "180ms" }} />

              <form onSubmit={handleSubmit} className="login-entra mt-8 flex flex-col gap-3" style={{ animationDelay: "220ms" }}>
                <label htmlFor="login-email" className="sr-only">Tu correo</label>
                <input
                  id="login-email"
                  type="email"
                  required
                  placeholder="tu@correo.com"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="login-campo"
                />
                <label htmlFor="login-password" className="sr-only">Tu contraseña</label>
                <input
                  id="login-password"
                  type="password"
                  required
                  placeholder="Tu contraseña"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="login-campo"
                />
                <button type="submit" disabled={loading} className="login-btn login-btn-tinta mt-1">
                  <span aria-hidden className="login-glifo">
                    <AtiendeMark className="h-[17px] w-auto brightness-0 invert" />
                  </span>
                  <span>{loading ? "Entrando…" : "Entrar al portal"}</span>
                </button>
              </form>

              <p className="login-entra mt-7 text-pretty text-[14px] leading-relaxed text-muted-foreground" style={{ animationDelay: "320ms" }}>
                ¿No tienes acceso todavía?{" "}
                <span className="font-semibold text-foreground">Pídele a tu despacho que te dé de alta.</span>
              </p>
            </div>
          </div>
        </div>
      </section>

      <aside className="hidden lg:flex lg:flex-col lg:py-10 lg:pl-6 lg:pr-10">
        <figure className="login-lamina min-h-0 flex-1 flex items-center justify-center">
          <img
            src="/images/login-hero.png"
            alt="Escritorio de un despacho contable, papeles y una laptop en la hora azul."
            className="login-foto-marca absolute inset-0 w-full h-full object-cover"
          />
          <div className="login-velo" />
          <figcaption className="absolute inset-x-0 bottom-0 p-9 z-10">
            <p className="login-kicker" style={{ color: "color-mix(in srgb, white 78%, transparent)" }}>
              CFDIs y declaraciones, en piloto automático
            </p>
            <p className="login-serif mt-3.5 text-white" style={{ fontSize: "clamp(20px, 1.9vw, 27px)" }}>
              Despachos contables en México.
              <br />
              El cierre de mes, sin capturar a mano.
            </p>
          </figcaption>
        </figure>
      </aside>
    </main>
  );
};

export default Login;
