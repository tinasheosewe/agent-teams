import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Info,
} from "lucide-react";
import { useEventStore } from "../../stores/eventStore";
import type { Toast } from "../../stores/eventStore";
import { cn } from "../../lib/utils";

const TOAST_DURATION = 6000;
const MAX_VISIBLE = 3;

export function ToastRail() {
  const { toasts, dismissToast } = useEventStore();
  const visible = toasts.slice(-MAX_VISIBLE);

  // Auto-dismiss
  useEffect(() => {
    if (toasts.length === 0) return;
    const timers = toasts.map((t) => {
      const elapsed = Date.now() - t.createdAt;
      const remaining = Math.max(TOAST_DURATION - elapsed, 100);
      return setTimeout(() => dismissToast(t.id), remaining);
    });
    return () => timers.forEach(clearTimeout);
  }, [toasts, dismissToast]);

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col-reverse gap-2 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {visible.map((toast) => (
          <ToastCard
            key={toast.id}
            toast={toast}
            onDismiss={() => dismissToast(toast.id)}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const borderColor = {
    error: "border-l-[#ff3b30]",
    warning: "border-l-[#ff9500]",
    info: "border-l-[#0071e3]",
    success: "border-l-[#34c759]",
  }[toast.kind];

  const Icon = {
    error: AlertCircle,
    warning: AlertTriangle,
    info: Info,
    success: CheckCircle2,
  }[toast.kind];

  const iconColor = {
    error: "text-[#ff3b30]",
    warning: "text-[#ff9500]",
    info: "text-[#0071e3]",
    success: "text-[#34c759]",
  }[toast.kind];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 60, scale: 0.95 }}
      transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
      className={cn(
        "pointer-events-auto w-[340px] rounded-xl bg-white/95 backdrop-blur-xl",
        "shadow-[0_8px_32px_rgba(0,0,0,0.08),0_0_1px_rgba(0,0,0,0.06)]",
        "border border-[rgba(0,0,0,0.06)] border-l-[3px]",
        borderColor,
        "overflow-hidden"
      )}
    >
      <div className="flex items-start gap-2.5 px-3.5 py-3">
        <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", iconColor)} />
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-[#1d1d1f]">{toast.title}</p>
          {toast.detail && (
            <p className="text-[12px] text-[#6e6e73] line-clamp-2 mt-0.5">{toast.detail}</p>
          )}
        </div>
        <button
          onClick={onDismiss}
          className="p-0.5 rounded text-[#86868b] hover:text-[#1d1d1f] transition-colors shrink-0"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Auto-dismiss progress bar */}
      <div className="h-[2px] bg-[rgba(0,0,0,0.04)]">
        <motion.div
          initial={{ width: "100%" }}
          animate={{ width: "0%" }}
          transition={{ duration: TOAST_DURATION / 1000, ease: "linear" }}
          className={cn("h-full", {
            "bg-[#ff3b30]/40": toast.kind === "error",
            "bg-[#ff9500]/40": toast.kind === "warning",
            "bg-[#0071e3]/40": toast.kind === "info",
            "bg-[#34c759]/40": toast.kind === "success",
          })}
        />
      </div>
    </motion.div>
  );
}
