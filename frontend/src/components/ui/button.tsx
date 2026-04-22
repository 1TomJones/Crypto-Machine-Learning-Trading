import { cn } from "../../lib/utils";

type Variant = "primary" | "secondary" | "danger" | "ghost";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
}

const variants: Record<Variant, string> = {
  primary:   "bg-brand-500 hover:bg-sky-400 text-white",
  secondary: "bg-gray-700 hover:bg-gray-600 text-gray-100",
  danger:    "bg-red-600 hover:bg-red-500 text-white",
  ghost:     "hover:bg-gray-800 text-gray-300",
};
const sizes = { sm: "px-2 py-1 text-xs", md: "px-3 py-1.5 text-sm", lg: "px-4 py-2 text-base" };

export function Button({ variant = "primary", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        variants[variant], sizes[size], className
      )}
      {...props}
    />
  );
}
