import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 font-medium whitespace-nowrap transition-colors",
  {
    variants: {
      variant: {
        success: "bg-[rgba(52,199,89,0.1)] text-[#248a3d]",
        warning: "bg-[rgba(255,159,10,0.1)] text-[#c93400]",
        error: "bg-[rgba(255,59,48,0.1)] text-[#ff3b30]",
        info: "bg-[rgba(0,113,227,0.08)] text-[#0071e3]",
        neutral: "bg-[rgba(0,0,0,0.05)] text-[#6e6e73]",
      },
      size: {
        sm: "px-1.5 py-0.5 text-[10px] rounded-[5px]",
        md: "px-2 py-0.5 text-[11px] rounded-md",
        lg: "px-2.5 py-1 text-[12px] rounded-lg",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "md",
    },
  }
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, size, className }))} {...props} />;
}

// Status-specific badge with animated dot for "running"
const STATUS_MAP: Record<string, { variant: "success" | "warning" | "error" | "info" | "neutral"; label: string }> = {
  running: { variant: "success", label: "Running" },
  completed: { variant: "info", label: "Completed" },
  failed: { variant: "error", label: "Failed" },
  paused: { variant: "warning", label: "Paused" },
  created: { variant: "neutral", label: "Created" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const mapping = STATUS_MAP[status] ?? { variant: "neutral" as const, label: status };
  return (
    <Badge variant={mapping.variant} size="md" className={cn("gap-1.5", className)}>
      {status === "running" && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#34c759] opacity-75" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#34c759]" />
        </span>
      )}
      {status !== "running" && (
        <span
          className="inline-flex h-1.5 w-1.5 rounded-full"
          style={{
            backgroundColor:
              status === "completed" ? "#0071e3" : status === "failed" ? "#ff3b30" : status === "paused" ? "#ff9500" : "#86868b",
          }}
        />
      )}
      {mapping.label}
    </Badge>
  );
}
