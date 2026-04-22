import { cn } from "../../lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-100",
        "focus:outline-none focus:ring-1 focus:ring-sky-500",
        className
      )}
      {...props}
    />
  );
}
