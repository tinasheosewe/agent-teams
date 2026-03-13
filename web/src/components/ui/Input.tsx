import * as React from "react";
import { cn } from "../../lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-[10px] bg-[#f5f5f7] px-3 text-[13px] text-[#1d1d1f]",
        "border border-transparent transition-all duration-200",
        "placeholder:text-[#86868b]",
        "focus:outline-none focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/20 focus:bg-white",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

export { Input };
