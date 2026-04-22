import { cn } from "../../lib/utils";

type Color = "green" | "red" | "yellow" | "blue" | "gray";
const colors: Record<Color, string> = {
  green:  "bg-green-900/50 text-green-400 border-green-800",
  red:    "bg-red-900/50 text-red-400 border-red-800",
  yellow: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  blue:   "bg-blue-900/50 text-blue-400 border-blue-800",
  gray:   "bg-gray-800 text-gray-400 border-gray-700",
};

export function Badge({ color = "gray", children, className }: { color?: Color; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-block rounded border px-1.5 py-0.5 text-xs font-medium", colors[color], className)}>
      {children}
    </span>
  );
}
