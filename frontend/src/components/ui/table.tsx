import { cn } from "../../lib/utils";

export function Table({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full text-sm text-left", className)}>{children}</table>
    </div>
  );
}
export function Thead({ children }: { children: React.ReactNode }) {
  return <thead className="text-xs text-gray-400 uppercase border-b border-gray-800">{children}</thead>;
}
export function Tbody({ children }: { children: React.ReactNode }) {
  return <tbody className="divide-y divide-gray-800/50">{children}</tbody>;
}
export function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return <th className={cn("px-3 py-2 font-medium", className)}>{children}</th>;
}
export function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn("px-3 py-2 text-gray-300", className)}>{children}</td>;
}
export function Tr({ children, className }: { children: React.ReactNode; className?: string }) {
  return <tr className={cn("hover:bg-gray-800/30 transition-colors", className)}>{children}</tr>;
}
