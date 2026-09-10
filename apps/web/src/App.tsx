import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { Layout } from "@/components/Layout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Cfdis from "@/pages/Cfdis";
import InvoiceDetail from "@/pages/InvoiceDetail";
import Declaraciones from "@/pages/Declaraciones";
import Reportes from "@/pages/Reportes";
import Configuracion from "@/pages/Configuracion";
import NotFound from "@/pages/NotFound";

function RutaProtegida({ children }: { children: React.ReactNode }) {
  const { estado } = useAuth();
  if (estado === "cargando") {
    return (
      <div className="min-h-screen flex items-center justify-center text-[13px] text-muted-foreground">
        Cargando panel…
      </div>
    );
  }
  if (estado === "anonimo") {
    return <Navigate to="/login" replace />;
  }
  return <Layout>{children}</Layout>;
}

const App = () => (
  <AuthProvider>
    <Toaster />
    <Sonner />
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<RutaProtegida><Dashboard /></RutaProtegida>} />
        <Route path="/cfdis" element={<RutaProtegida><Cfdis /></RutaProtegida>} />
        <Route path="/cfdis/:id" element={<RutaProtegida><InvoiceDetail /></RutaProtegida>} />
        <Route path="/declaraciones" element={<RutaProtegida><Declaraciones /></RutaProtegida>} />
        <Route path="/reportes" element={<RutaProtegida><Reportes /></RutaProtegida>} />
        <Route path="/configuracion" element={<RutaProtegida><Configuracion /></RutaProtegida>} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  </AuthProvider>
);

export default App;
