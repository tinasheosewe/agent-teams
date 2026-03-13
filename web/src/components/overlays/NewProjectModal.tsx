import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Sparkles, Users } from "lucide-react";
import * as RadixDialog from "@radix-ui/react-dialog";
import { useConfigStore } from "../../stores/configStore";
import { useProjectStore } from "../../stores/projectStore";
import { useUiStore } from "../../stores/uiStore";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { cn } from "../../lib/utils";

export function NewProjectModal() {
  const { showNewProject, setShowNewProject, navigateTo } = useUiStore();
  const { configs, fetchConfigs } = useConfigStore();
  const { createProject, setActiveProject } = useProjectStore();

  const [prompt, setPrompt] = useState("");
  const [selectedConfig, setSelectedConfig] = useState<string>("");
  const [mode, setMode] = useState<"interactive" | "autonomous">("interactive");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (showNewProject && configs.length === 0) fetchConfigs();
  }, [showNewProject]);

  // Default to first config
  useEffect(() => {
    if (!selectedConfig && configs.length > 0) {
      setSelectedConfig(configs[0].path);
    }
  }, [configs, selectedConfig]);

  const handleCreate = async () => {
    if (!prompt.trim() || !selectedConfig) return;
    setLoading(true);
    try {
      const project = await createProject(prompt.trim(), selectedConfig);
      setActiveProject(project.id);
      setShowNewProject(false);
      navigateTo("project");
      setPrompt("");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && prompt.trim()) {
      e.preventDefault();
      handleCreate();
    }
  };

  return (
    <RadixDialog.Root open={showNewProject} onOpenChange={setShowNewProject}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/20 backdrop-blur-sm"
          />
        </RadixDialog.Overlay>
        <RadixDialog.Content asChild>
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: -10 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: -10 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[580px] max-h-[85vh] rounded-2xl bg-white/95 backdrop-blur-xl shadow-[0_24px_80px_rgba(0,0,0,0.12),0_0_1px_rgba(0,0,0,0.08)] border border-[rgba(0,0,0,0.06)] overflow-hidden flex flex-col"
            onKeyDown={handleKeyDown}
          >
            {/* Header */}
            <div className="px-6 pt-6 pb-2">
              <RadixDialog.Title className="text-[18px] font-semibold text-[#1d1d1f] flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-[#0071e3]" />
                New Project
              </RadixDialog.Title>
              <RadixDialog.Description className="text-[13px] text-[#86868b] mt-1">
                Choose a configuration and describe what you want built.
              </RadixDialog.Description>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-auto px-6 py-4 space-y-5">
              {/* Config selector */}
              <div>
                <label className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider block mb-2">
                  Configuration
                </label>
                <div className="grid grid-cols-1 gap-2">
                  {configs.map((cfg) => (
                    <button
                      key={cfg.path}
                      onClick={() => setSelectedConfig(cfg.path)}
                      className={cn(
                        "w-full text-left p-3 rounded-xl border transition-all",
                        selectedConfig === cfg.path
                          ? "border-[#0071e3] bg-[#0071e3]/4 shadow-[0_0_0_1px_#0071e3]"
                          : "border-[rgba(0,0,0,0.06)] hover:border-[rgba(0,0,0,0.12)] hover:bg-[rgba(0,0,0,0.02)]"
                      )}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[14px] font-semibold text-[#1d1d1f]">{cfg.name}</span>
                        <span className="text-[11px] text-[#86868b] flex items-center gap-1">
                          <Users className="h-3 w-3" /> {cfg.teams.length} teams
                        </span>
                      </div>
                      <p className="text-[12px] text-[#6e6e73] line-clamp-2">{cfg.description}</p>
                      <div className="flex gap-1.5 mt-2 flex-wrap">
                        {cfg.teams.map((t) => (
                          <Badge key={t} variant="neutral" size="sm">{t}</Badge>
                        ))}
                      </div>
                    </button>
                  ))}
                  {configs.length === 0 && (
                    <p className="text-center py-4 text-[13px] text-[#86868b]">Loading configs…</p>
                  )}
                </div>
              </div>

              {/* Prompt */}
              <div>
                <label className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider block mb-2">
                  Prompt
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe what you want the agents to build…"
                  rows={4}
                  className="w-full rounded-xl border border-[rgba(0,0,0,0.08)] bg-[#f5f5f7] px-4 py-3 text-[14px] text-[#1d1d1f] placeholder:text-[#86868b] resize-none focus:outline-none focus:ring-2 focus:ring-[#0071e3]/30 focus:border-[#0071e3]/50 transition-shadow"
                />
              </div>

              {/* Mode selector */}
              <div>
                <label className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider block mb-2">
                  Mode
                </label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setMode("interactive")}
                    className={cn(
                      "flex-1 px-4 py-2.5 rounded-xl text-[13px] font-medium border transition-all text-center",
                      mode === "interactive"
                        ? "border-[#0071e3] bg-[#0071e3]/4 text-[#0071e3] shadow-[0_0_0_1px_#0071e3]"
                        : "border-[rgba(0,0,0,0.06)] text-[#6e6e73] hover:border-[rgba(0,0,0,0.12)]"
                    )}
                  >
                    Interactive
                  </button>
                  <button
                    onClick={() => setMode("autonomous")}
                    className={cn(
                      "flex-1 px-4 py-2.5 rounded-xl text-[13px] font-medium border transition-all text-center",
                      mode === "autonomous"
                        ? "border-[#0071e3] bg-[#0071e3]/4 text-[#0071e3] shadow-[0_0_0_1px_#0071e3]"
                        : "border-[rgba(0,0,0,0.06)] text-[#6e6e73] hover:border-[rgba(0,0,0,0.12)]"
                    )}
                  >
                    Autonomous
                  </button>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-[rgba(0,0,0,0.06)] flex items-center justify-between bg-[#f5f5f7]/50">
              <span className="text-[11px] text-[#86868b] flex items-center gap-1">
                <kbd className="px-1 py-0.5 rounded bg-[rgba(0,0,0,0.06)] text-[9px] font-medium">⌘</kbd>
                <kbd className="px-1 py-0.5 rounded bg-[rgba(0,0,0,0.06)] text-[9px] font-medium">↵</kbd>
                to create
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() => setShowNewProject(false)}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={handleCreate}
                  loading={loading}
                  disabled={!prompt.trim() || !selectedConfig}
                >
                  Create & Run
                </Button>
              </div>
            </div>
          </motion.div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
