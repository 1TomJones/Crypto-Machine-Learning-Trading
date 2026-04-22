import { cn } from "../../lib/utils";

type AlertVariant = "info" | "warning" | "error" | "success";
const styles: Record<AlertVariant, string> = {
  info:    "border-blue-800 bg-blue-900/30 text-blue-300",
  warning: "border-yellow-800 bg-yellow-900/30 text-yellow-300",
  error:   "border-red-800 bg-red-900/30 text-red-300",
  success: "border-green-800 bg-green-900/30 text-green-300",
};

export function Alert({ variant = "info", children, className }: {
  variant?: AlertVariant; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("rounded-lg border p-3 text-sm", styles[variant], className)}>
      {children}
    </div>
  );
}
