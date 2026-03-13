import { cn } from "../../lib/utils";

interface ProgressProps {
  value: number; // 0 to 1
  className?: string;
  color?: string;
}

export function Progress({ value, className, color }: ProgressProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const barColor =
    color ?? (value >= 0.7 ? "#34c759" : value >= 0.4 ? "#ff9500" : "#ff3b30");

  return (
    <div className={cn("h-1.5 w-full rounded-full bg-[rgba(0,0,0,0.06)] overflow-hidden", className)}>
      <div
        className="h-full rounded-full transition-all duration-500 ease-out"
        style={{ width: `${pct}%`, backgroundColor: barColor }}
      />
    </div>
  );
}

interface ConfidenceRingProps {
  value: number; // 0 to 1
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export function ConfidenceRing({ value, size = 32, strokeWidth = 3, className }: ConfidenceRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(1, value)));
  const color = value >= 0.7 ? "#34c759" : value >= 0.4 ? "#ff9500" : "#ff3b30";

  return (
    <svg width={size} height={size} className={cn("shrink-0", className)}>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(0,0,0,0.06)"
        strokeWidth={strokeWidth}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        className="transition-all duration-500 ease-out"
      />
    </svg>
  );
}
