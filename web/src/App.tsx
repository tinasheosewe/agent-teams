import { useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { useUiStore } from "./stores/uiStore";
import { useProjectStore } from "./stores/projectStore";
import { useConfigStore } from "./stores/configStore";
import { useEventStore } from "./stores/eventStore";
import { Navbar } from "./components/layout/Navbar";
import { DashboardView } from "./views/DashboardView";
import { ProjectDetailView } from "./views/ProjectDetailView";
import { CommandPalette } from "./components/overlays/CommandPalette";
import { NewProjectModal } from "./components/overlays/NewProjectModal";
import { ToastRail } from "./components/overlays/ToastRail";

export default function App() {
  const { view, togglePalette } = useUiStore();
  const { fetchProjects } = useProjectStore();
  const { fetchConfigs } = useConfigStore();
  const { disconnectAll } = useEventStore();

  // Boot: fetch projects + configs
  useEffect(() => {
    fetchProjects();
    fetchConfigs();
    return () => disconnectAll();
  }, []);

  // ⌘K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        togglePalette();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePalette]);

  return (
    <div className="h-screen flex flex-col bg-[#fafafa] text-[#1d1d1f] antialiased">
      <Navbar />
      <AnimatePresence mode="wait">
        {view === "dashboard" ? (
          <DashboardView key="dashboard" />
        ) : (
          <ProjectDetailView key="detail" />
        )}
      </AnimatePresence>
      <CommandPalette />
      <NewProjectModal />
      <ToastRail />
    </div>
  );
}
