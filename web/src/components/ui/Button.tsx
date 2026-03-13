import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";
import { Loader2 } from "lucide-react";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 cursor-pointer select-none whitespace-nowrap disabled:pointer-events-none disabled:opacity-50 active:scale-[0.97]",
  {
    variants: {
      variant: {
        primary:
          "bg-[#0071e3] text-white shadow-sm hover:bg-[#0077ED] focus-visible:ring-2 focus-visible:ring-[#0071e3]/40 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
        secondary:
          "bg-[#f5f5f7] text-[#1d1d1f] border border-[rgba(0,0,0,0.06)] hover:bg-[#e8e8ed] focus-visible:ring-2 focus-visible:ring-[#0071e3]/30",
        ghost:
          "text-[#6e6e73] hover:text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.04)] focus-visible:ring-2 focus-visible:ring-[#0071e3]/30",
        destructive:
          "text-[#ff3b30] hover:bg-[rgba(255,59,48,0.08)] focus-visible:ring-2 focus-visible:ring-[#ff3b30]/30",
        outline:
          "border border-[rgba(0,0,0,0.12)] text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.03)] focus-visible:ring-2 focus-visible:ring-[#0071e3]/30",
      },
      size: {
        sm: "h-7 px-3 text-[12px] rounded-lg",
        md: "h-9 px-4 text-[13px] rounded-[10px]",
        lg: "h-11 px-6 text-[14px] rounded-xl",
        icon: "h-8 w-8 rounded-lg",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, children, disabled, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(buttonVariants({ variant, size, className }))}
        disabled={disabled || loading}
        {...props}
      >
        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
