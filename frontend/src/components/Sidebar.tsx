import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, TrendingUp, Cpu, FlaskConical,
  History, Radio, ShieldAlert, LogOut,
} from "lucide-react";
import { useAuthStore } from "../lib/store";

const links = [
  { to: "/",            label: "Dashboard",    icon: LayoutDashboard },
  { to: "/markets",     label: "Markets",      icon: TrendingUp },
  { to: "/strategies",  label: "Strategies",   icon: Cpu },
  { to: "/model-builder", label: "Train Model", icon: FlaskConical },
  { to: "/backtests",   label: "Backtests",    icon: History },
  { to: "/live",        label: "Live Trading", icon: Radio },
  { to: "/risk",        label: "Risk",         icon: ShieldAlert },
];

export default function Sidebar() {
  const logout = useAuthStore((s) => s.logout);
  return (
    <aside className="flex h-screen w-60 flex-col border-r border-gray-800 bg-gray-900">
      <div className="px-4 py-5">
        <span className="text-lg font-bold text-sky-400">Crypto ML</span>
      </div>
      <nav className="flex-1 space-y-0.5 px-2">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-sky-900/40 text-sky-400"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-2">
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-400 hover:bg-gray-800 hover:text-red-400 transition-colors"
        >
          <LogOut size={16} /> Logout
        </button>
      </div>
    </aside>
  );
}
