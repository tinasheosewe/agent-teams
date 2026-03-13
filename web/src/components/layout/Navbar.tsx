import { Search, Plus } from "lucide-react";
import { Button } from "../ui/Button";
import { useUiStore } from "../../stores/uiStore";
import { cn } from "../../lib/utils";

export function Navbar() {
  const { view, navigateTo, togglePalette, setShowNewProject } = useUiStore();

  return (
    <header
      className={cn(
        "sticky top-0 z-40 h-12 shrink-0",
        "flex items-center justify-between px-5",
        "bg-white/72 backdrop-blur-xl",
        "border-b border-[rgba(0,0,0,0.06)]"
      )}
    >
      {/* Left: Brand */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigateTo("dashboard")}
          className="flex items-center gap-2 text-[15px] font-semibold text-[#1d1d1f] hover:opacity-70 transition-opacity"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#0071e3] to-[#5856d6] text-white text-[11px] font-bold">
            AA
          </span>
          <span className="hidden sm:inline">AgentAgent</span>
        </button>

        {view === "project" && (
          <div className="flex items-center gap-1 text-[13px] text-[#86868b]">
            <span>/</span>
            <span className="text-[#6e6e73]">Project</span>
          </div>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        <button
          onClick={togglePalette}
          className={cn(
            "hidden sm:flex items-center gap-2 h-8 px-3 rounded-lg",
            "bg-[#f5f5f7] text-[12px] text-[#86868b]",
            "border border-[rgba(0,0,0,0.04)] hover:border-[rgba(0,0,0,0.1)]",
            "transition-all duration-200 cursor-pointer"
          )}
        >
          <Search className="h-3.5 w-3.5" />
          <span>Search</span>
          <kbd className="ml-2 flex h-5 items-center rounded border border-[rgba(0,0,0,0.08)] bg-white px-1.5 text-[10px] font-medium text-[#86868b]">
            ⌘K
          </kbd>
        </button>

        <Button
          variant="primary"
          size="sm"
          onClick={() => setShowNewProject(true)}
          className="gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">New Project</span>
        </Button>
      </div>
    </header>
  );
}
