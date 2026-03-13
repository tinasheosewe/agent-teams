import { useEffect, useMemo, useCallback } from "react";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Play,
  Pause,
  Square,
  RotateCcw,
  PanelRightOpen,
  PanelRightClose,
  List,
  Pin,
} from "lucide-react";
import { useProjectStore } from "../stores/projectStore";
import { useEventStore } from "../stores/eventStore";
import { useUiStore } from "../stores/uiStore";
import { Button } from "../components/ui/Button";
import { StatusBadge } from "../components/ui/Badge";
import { Badge } from "../components/ui/Badge";
import { PipelineDAG } from "../components/detail/PipelineDAG";
import { TimelineStream } from "../components/detail/TimelineStream";
import { BoardPanel } from "../components/detail/BoardPanel";
import { ContextPanel } from "../components/detail/ContextPanel";
import { InputBar } from "../components/detail/InputBar";
import * as api from "../api";

export function ProjectDetailView() {
  const {
    activeProject,
    decisions,
    artifacts,
    fetchDecisions,
    fetchArtifacts,
    fetchProject,
    runProject,
    pauseProject,
    resumeProject,
    killProject,
  } = useProjectStore();
  const { navigateTo, selectedStep, selectStep, contextPanelOpen, setContextPanelOpen, timelineGrouped, setTimelineGrouped, contentView, setContentView } = useUiStore();
  const { connectProject, disconnectProject, getEvents, sendMessage } = useEventStore();

  const project = activeProject();
  const projectId = project?.id;
  const events = projectId ? getEvents(projectId) : [];
  const projectDecisions = projectId ? decisions.get(projectId) ?? [] : [];
  const projectArtifacts = projectId ? artifacts.get(projectId) ?? [] : [];

  // Fetch data + connect WS
  useEffect(() => {
    if (!projectId) return;
    fetchDecisions(projectId);
    fetchArtifacts(projectId);
    connectProject(projectId);

    // Poll for project status updates
    const interval = setInterval(() => {
      fetchProject(projectId);
      fetchDecisions(projectId);
      fetchArtifacts(projectId);
    }, 5000);

    return () => {
      clearInterval(interval);
    };
  }, [projectId]);

  // Detect if input is requested
  const inputState = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.type === "user_input_requested") {
        return { requested: true, prompt: e.data.question as string };
      }
      if (e.type === "user_input_received") {
        return { requested: false, prompt: undefined };
      }
    }
    return { requested: false, prompt: undefined };
  }, [events]);

  // Handlers
  const handleBack = useCallback(() => {
    if (projectId) disconnectProject(projectId);
    selectStep(null);
    navigateTo("dashboard");
  }, [projectId, disconnectProject, selectStep, navigateTo]);

  const handleSend = useCallback(
    (message: string) => {
      if (projectId) sendMessage(projectId, "message", message);
    },
    [projectId, sendMessage]
  );

  const handleConstrain = useCallback(
    (message: string) => {
      if (projectId) sendMessage(projectId, "constrain", message);
    },
    [projectId, sendMessage]
  );

  const handleVetoDecision = useCallback(
    (decisionId: string) => {
      if (projectId) {
        api.sendMessage(projectId, `veto:${decisionId}`, "veto");
      }
    },
    [projectId]
  );

  const handleVetoLast = useCallback(() => {
    const last = projectDecisions.filter((d) => d.status === "active").pop();
    if (last) handleVetoDecision(last.id);
  }, [projectDecisions, handleVetoDecision]);

  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-[#86868b] text-[14px]">
        No project selected
      </div>
    );
  }

  const isRunning = project.status === "running";
  const isPaused = project.status === "paused";

  return (
    <motion.div
      initial={{ x: 60, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 60, opacity: 0 }}
      transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
      className="flex-1 flex flex-col overflow-hidden bg-[#fafafa]"
    >
      {/* Top bar */}
      <header className="shrink-0 h-12 px-4 flex items-center gap-3 border-b border-[rgba(0,0,0,0.06)] bg-white/80 backdrop-blur-xl">
        {/* Back */}
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-[13px] text-[#0071e3] hover:text-[#0077ed] transition-colors font-medium"
        >
          <ArrowLeft className="h-4 w-4" />
          Dashboard
        </button>

        {/* Separator */}
        <div className="w-px h-5 bg-[rgba(0,0,0,0.08)]" />

        {/* Project info */}
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <StatusBadge status={project.status} />
          <span className="text-[13px] font-medium text-[#1d1d1f] truncate max-w-md">
            {project.prompt}
          </span>
          <Badge variant="neutral" size="sm" className="shrink-0">
            {project.config_name}
          </Badge>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5">
          {project.status === "created" && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => runProject(project.id)}
            >
              <Play className="h-3.5 w-3.5 mr-1" /> Run
            </Button>
          )}
          {isRunning && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => pauseProject(project.id)}
            >
              <Pause className="h-3.5 w-3.5 mr-1" /> Pause
            </Button>
          )}
          {isPaused && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => resumeProject(project.id)}
            >
              <RotateCcw className="h-3.5 w-3.5 mr-1" /> Resume
            </Button>
          )}
          {(isRunning || isPaused) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => killProject(project.id)}
              className="text-[#ff3b30] hover:bg-[#ff3b30]/6"
            >
              <Square className="h-3.5 w-3.5 mr-1" /> Stop
            </Button>
          )}
          {/* View toggle: Timeline / Board */}
          <div className="flex items-center rounded-lg bg-[#f5f5f7] p-0.5">
            <button
              onClick={() => setContentView("timeline")}
              className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                contentView === "timeline" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#86868b]"
              }`}
            >
              <List className="h-3 w-3 inline-block mr-1" />Timeline
            </button>
            <button
              onClick={() => setContentView("board")}
              className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                contentView === "board" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#86868b]"
              }`}
            >
              <Pin className="h-3 w-3 inline-block mr-1" />Board
            </button>
          </div>
          <button
            onClick={() => setContextPanelOpen(!contextPanelOpen)}
            className="p-1.5 rounded-lg text-[#86868b] hover:text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.04)] transition-colors"
            title={contextPanelOpen ? "Close panel" : "Open panel"}
          >
            {contextPanelOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </button>
        </div>
      </header>

      {/* DAG strip */}
      <div className="shrink-0 h-[140px] border-b border-[rgba(0,0,0,0.06)] bg-white">
        <PipelineDAG
          events={events}
          selectedStep={selectedStep}
          onSelectStep={selectStep}
        />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Timeline / Board view */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {contentView === "board" ? (
            <BoardPanel events={events} />
          ) : (
            <TimelineStream
              events={events}
              selectedStep={selectedStep}
              grouped={timelineGrouped}
              onToggleGrouped={() => setTimelineGrouped(!timelineGrouped)}
            />
          )}
        </div>

        {/* Context panel */}
        <ContextPanel
          projectId={project.id}
          selectedStep={selectedStep}
          events={events}
          decisions={projectDecisions}
          artifacts={projectArtifacts}
          open={contextPanelOpen}
          onClose={() => setContextPanelOpen(false)}
          onVeto={handleVetoDecision}
        />
      </div>

      {/* Input bar */}
      <InputBar
        inputRequested={inputState.requested}
        inputPrompt={inputState.prompt}
        onSend={handleSend}
        onConstrain={handleConstrain}
        onVetoLast={handleVetoLast}
        disabled={!isRunning && !inputState.requested}
      />
    </motion.div>
  );
}
