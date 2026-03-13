import { create } from "zustand";

type View = "dashboard" | "project";
type ContextTab = "rounds" | "decisions" | "artifacts" | "gate" | "transcript";

interface UiState {
  view: View;
  showCommandPalette: boolean;
  showNewProject: boolean;
  selectedStep: string | null;
  contextTab: ContextTab;
  contextPanelOpen: boolean;
  timelineGrouped: boolean;

  navigateTo: (view: View) => void;
  togglePalette: () => void;
  setShowNewProject: (show: boolean) => void;
  selectStep: (step: string | null) => void;
  setContextTab: (tab: ContextTab) => void;
  setContextPanelOpen: (open: boolean) => void;
  setTimelineGrouped: (grouped: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  view: "dashboard",
  showCommandPalette: false,
  showNewProject: false,
  selectedStep: null,
  contextTab: "decisions",
  contextPanelOpen: true,
  timelineGrouped: true,

  navigateTo: (view) => set({ view }),
  togglePalette: () => set((s) => ({ showCommandPalette: !s.showCommandPalette })),
  setShowNewProject: (show) => set({ showNewProject: show }),
  selectStep: (step) => set({ selectedStep: step }),
  setContextTab: (tab) => set({ contextTab: tab }),
  setContextPanelOpen: (open) => set({ contextPanelOpen: open }),
  setTimelineGrouped: (grouped) => set({ timelineGrouped: grouped }),
}));
