import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Markets from "./pages/Markets";
import Strategies from "./pages/Strategies";
import ModelBuilder from "./pages/ModelBuilder";
import Backtests from "./pages/Backtests";
import LiveDeployment from "./pages/LiveDeployment";
import RiskSettings from "./pages/RiskSettings";
import Login from "./pages/Login";
import { useAuthStore } from "./lib/store";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="markets" element={<Markets />} />
          <Route path="strategies" element={<Strategies />} />
          <Route path="model-builder" element={<ModelBuilder />} />
          <Route path="backtests" element={<Backtests />} />
          <Route path="live" element={<LiveDeployment />} />
          <Route path="risk" element={<RiskSettings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
