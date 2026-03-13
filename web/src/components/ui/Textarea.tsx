import * as React from "react";
import { cn } from "../../lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex w-full rounded-xl bg-[#f5f5f7] px-4 py-3 text-[13px] text-[#1d1d1f]",
        "border border-transparent transition-all duration-200 resize-none",
        "placeholder:text-[#86868b]",
        "focus:outline-none focus:border-[#0071e3] focus:ring-2 focus:ring-[#0071e3]/20 focus:bg-white",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className
      )}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";

export { Textarea };
