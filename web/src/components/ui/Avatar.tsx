import { cn, hashColor, initials } from "../../lib/utils";

interface AvatarProps {
  name: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const SIZE_MAP = {
  sm: "h-6 w-6 text-[10px]",
  md: "h-8 w-8 text-[11px]",
  lg: "h-10 w-10 text-[13px]",
};

export function Avatar({ name, size = "md", className }: AvatarProps) {
  const color = hashColor(name);
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full font-semibold text-white select-none shrink-0",
        SIZE_MAP[size],
        className
      )}
      style={{ backgroundColor: color }}
      title={name}
    >
      {initials(name)}
    </div>
  );
}
