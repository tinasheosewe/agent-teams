import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Play,
  Settings,
  FolderOpen,
  PlusCircle,
  ChevronRight,
} from "lucide-react";
import { useProjectStore } from "../../stores/projectStore";
import { useConfigStore } from "../../stores/configStore";
import { useUiStore } from "../../stores/uiStore";
import { StatusBadge } from "../ui/Badge";
import { cn } from "../../lib/utils";

export function CommandPalette() {
  const { showCommandPalette, togglePalette, navigateTo, setShowNewProject } = useUiStore();
  const { projectList, setActiveProject } = useProjectStore();
  const { configs } = useConfigStore();

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset on open
  useEffect(() => {
    if (showCommandPalette) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [showCommandPalette]);

  // Build result items
  const items = useMemo(() => {
    const q = query.toLowerCase().trim();
    const results: PaletteItem[] = [];

    // Actions
    const actions: PaletteItem[] = [
      { kind: "action", id: "new-project", label: "New Project", icon: "plus", action: () => { togglePalette(); setShowNewProject(true); } },
      { kind: "action", id: "dashboard", label: "Go to Dashboard", icon: "folder", action: () => { togglePalette(); navigateTo("dashboard"); } },
    ];

    for (const a of actions) {
      if (!q || a.label.toLowerCase().includes(q)) results.push(a);
    }

    // Projects
    const projects = projectList();
    for (const p of projects) {
      if (q && !p.prompt.toLowerCase().includes(q) && !p.config_name.toLowerCase().includes(q)) continue;
      results.push({
        kind: "project",
        id: p.id,
        label: p.prompt.slice(0, 80),
        status: p.status,
        config: p.config_name,
        action: () => {
          togglePalette();
          setActiveProject(p.id);
          navigateTo("project");
        },
      });
    }

    // Configs
    for (const c of configs) {
      if (q && !c.name.toLowerCase().includes(q) && !c.description.toLowerCase().includes(q)) continue;
      results.push({
        kind: "config",
        id: c.name,
        label: c.name,
        description: c.description,
        teams: c.teams,
        action: () => {
          togglePalette();
          setShowNewProject(true);
        },
      });
    }

    return results.slice(0, 20);
  }, [query, projectList, configs, togglePalette, setShowNewProject, navigateTo, setActiveProject]);

  // Clamp selection
  useEffect(() => {
    if (selectedIndex >= items.length) setSelectedIndex(Math.max(0, items.length - 1));
  }, [items.length, selectedIndex]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, items.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        items[selectedIndex]?.action();
      } else if (e.key === "Escape") {
        togglePalette();
      }
    },
    [items, selectedIndex, togglePalette]
  );

  if (!showCommandPalette) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
        onClick={() => togglePalette()}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" />

        {/* Palette */}
        <motion.div
          initial={{ scale: 0.95, opacity: 0, y: -10 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.95, opacity: 0, y: -10 }}
          transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
          onClick={(e) => e.stopPropagation()}
          className="relative w-[560px] max-h-[420px] rounded-2xl bg-white/95 backdrop-blur-xl shadow-[0_24px_80px_rgba(0,0,0,0.12),0_0_1px_rgba(0,0,0,0.08)] border border-[rgba(0,0,0,0.06)] overflow-hidden flex flex-col"
        >
          {/* Search input */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-[rgba(0,0,0,0.06)]">
            <Search className="h-4 w-4 text-[#86868b] shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search projects, configs, actions…"
              className="flex-1 text-[14px] bg-transparent text-[#1d1d1f] placeholder:text-[#86868b] outline-none"
            />
            <kbd className="px-1.5 py-0.5 rounded bg-[rgba(0,0,0,0.06)] text-[10px] text-[#86868b] font-medium">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="flex-1 overflow-auto py-2">
            {items.length === 0 && (
              <p className="text-center text-[13px] text-[#86868b] py-8">No results</p>
            )}

            {/* Group rendering */}
            <ResultGroup
              label="Actions"
              items={items.filter((i) => i.kind === "action")}
              selectedIndex={selectedIndex}
              allItems={items}
            />
            <ResultGroup
              label="Projects"
              items={items.filter((i) => i.kind === "project")}
              selectedIndex={selectedIndex}
              allItems={items}
            />
            <ResultGroup
              label="Configs"
              items={items.filter((i) => i.kind === "config")}
              selectedIndex={selectedIndex}
              allItems={items}
            />
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// -- Types --
interface PaletteItem {
  kind: "action" | "project" | "config";
  id: string;
  label: string;
  icon?: string;
  status?: string;
  config?: string;
  description?: string;
  teams?: string[];
  action: () => void;
}

// -- Result group --
function ResultGroup({
  label,
  items,
  selectedIndex,
  allItems,
}: {
  label: string;
  items: PaletteItem[];
  selectedIndex: number;
  allItems: PaletteItem[];
}) {
  if (items.length === 0) return null;

  return (
    <div className="mb-1">
      <p className="px-4 py-1 text-[10px] font-semibold text-[#86868b] uppercase tracking-wider">
        {label}
      </p>
      {items.map((item) => {
        const globalIdx = allItems.indexOf(item);
        const selected = globalIdx === selectedIndex;

        return (
          <button
            key={item.id}
            onClick={item.action}
            className={cn(
              "w-full flex items-center gap-3 px-4 py-2 text-left transition-colors",
              selected ? "bg-[#0071e3]/8 text-[#0071e3]" : "hover:bg-[rgba(0,0,0,0.03)] text-[#1d1d1f]"
            )}
          >
            <ItemIcon item={item} selected={selected} />
            <div className="flex-1 min-w-0">
              <span className="text-[13px] font-medium truncate block">{item.label}</span>
              {item.description && (
                <span className="text-[11px] text-[#86868b] truncate block">{item.description}</span>
              )}
            </div>
            {item.status && <StatusBadge status={item.status} />}
            {item.config && !item.status && (
              <span className="text-[11px] text-[#86868b]">{item.config}</span>
            )}
            {item.teams && (
              <span className="text-[11px] text-[#86868b]">{item.teams.length} teams</span>
            )}
            <ChevronRight className="h-3 w-3 text-[#86868b] shrink-0" />
          </button>
        );
      })}
    </div>
  );
}

function ItemIcon({ item, selected }: { item: PaletteItem; selected: boolean }) {
  const cls = cn("h-4 w-4 shrink-0", selected ? "text-[#0071e3]" : "text-[#86868b]");
  if (item.kind === "action") {
    if (item.icon === "plus") return <PlusCircle className={cls} />;
    if (item.icon === "folder") return <FolderOpen className={cls} />;
    return <Settings className={cls} />;
  }
  if (item.kind === "project") return <Play className={cls} />;
  return <Settings className={cls} />;
}
