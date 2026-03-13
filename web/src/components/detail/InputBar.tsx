import { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, ShieldAlert, Ban, CornerDownLeft } from "lucide-react";
import { Button } from "../ui/Button";
import { cn } from "../../lib/utils";

interface Props {
  /** Whether the backend has requested user input */
  inputRequested: boolean;
  /** The prompt/question from the system */
  inputPrompt?: string;
  onSend: (message: string) => void;
  onConstrain: (message: string) => void;
  onVetoLast: () => void;
  disabled?: boolean;
}

export function InputBar({
  inputRequested,
  inputPrompt,
  onSend,
  onConstrain,
  onVetoLast,
  disabled,
}: Props) {
  const [value, setValue] = useState("");
  const [mode, setMode] = useState<"send" | "constrain">("send");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [value]);

  // Focus when input requested
  useEffect(() => {
    if (inputRequested) textareaRef.current?.focus();
  }, [inputRequested]);

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    if (mode === "constrain") {
      onConstrain(trimmed);
    } else {
      onSend(trimmed);
    }
    setValue("");
    setMode("send");
  }, [value, mode, disabled, onSend, onConstrain]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  return (
    <div className="shrink-0 border-t border-[rgba(0,0,0,0.06)]">
      {/* Input requested banner */}
      <AnimatePresence>
        {inputRequested && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 py-2 bg-[#e8f0fe] border-b border-[#b6d4fe]/40">
              <p className="text-[12px] font-medium text-[#0071e3] flex items-center gap-1.5">
                <CornerDownLeft className="h-3.5 w-3.5" />
                {inputPrompt || "Input requested — the system is waiting for your response"}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input area */}
      <div className="px-4 py-3 bg-white/90 backdrop-blur-xl">
        <div className="flex items-end gap-2">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                inputRequested
                  ? "Type your response…"
                  : "Send a message, constrain direction, or veto…"
              }
              disabled={disabled}
              rows={1}
              className={cn(
                "w-full resize-none rounded-xl border bg-[#f5f5f7] px-3 py-2.5 text-[13px] text-[#1d1d1f]",
                "placeholder:text-[#86868b] focus:outline-none focus:ring-2 focus:ring-[#0071e3]/30 focus:border-[#0071e3]/50",
                "transition-shadow duration-200",
                disabled && "opacity-50 cursor-not-allowed",
                "border-[rgba(0,0,0,0.08)]"
              )}
            />
            {/* ⌘Enter hint */}
            {value.length > 0 && (
              <span className="absolute right-2.5 bottom-2.5 text-[10px] text-[#86868b] pointer-events-none flex items-center gap-0.5">
                <kbd className="px-1 py-0.5 rounded bg-[rgba(0,0,0,0.06)] text-[9px] font-medium">⌘</kbd>
                <kbd className="px-1 py-0.5 rounded bg-[rgba(0,0,0,0.06)] text-[9px] font-medium">↵</kbd>
              </span>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5">
            {/* Send / Constrain toggle */}
            <Button
              variant={mode === "send" ? "primary" : "secondary"}
              size="icon"
              onClick={handleSubmit}
              disabled={!value.trim() || disabled}
              title={mode === "send" ? "Send message" : "Send constraint"}
            >
              {mode === "send" ? (
                <Send className="h-4 w-4" />
              ) : (
                <ShieldAlert className="h-4 w-4" />
              )}
            </Button>

            {/* Mode toggle */}
            <button
              onClick={() => setMode(mode === "send" ? "constrain" : "send")}
              className={cn(
                "h-9 px-2 rounded-lg text-[10px] font-medium transition-colors",
                mode === "constrain"
                  ? "bg-[#ff9500]/10 text-[#ff9500]"
                  : "text-[#86868b] hover:text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.04)]"
              )}
              title={mode === "send" ? "Switch to constrain mode" : "Switch to send mode"}
            >
              {mode === "send" ? (
                <ShieldAlert className="h-3.5 w-3.5" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
            </button>

            {/* Veto last */}
            <button
              onClick={onVetoLast}
              disabled={disabled}
              className="h-9 px-2 rounded-lg text-[10px] font-medium text-[#86868b] hover:text-[#ff3b30] hover:bg-[#ff3b30]/6 transition-colors disabled:opacity-40"
              title="Veto last decision"
            >
              <Ban className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
