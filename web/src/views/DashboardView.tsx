import { useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Zap, Clock, DollarSign, MessageSquare, FileText, ChevronRight, Play, Pause, Square, ArrowRight } from "lucide-react";
import { useProjectStore } from "../stores/projectStore";
import { useConfigStore } from "../stores/configStore";
import { useUiStore } from "../stores/uiStore";
import { useEventStore } from "../stores/eventStore";
import { StatusBadge, Badge } from "../components/ui/Badge";
import { Card, CardContent } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { ScrollArea } from "../components/ui/ScrollArea";
import { Skeleton } from "../components/ui/Skeleton";
import { cn, relativeTime, formatCost, formatTokens } from "../lib/utils";
import type { Project } from "../api";

export function DashboardView() {
  const { projectList, fetchProjects, activeProjectId, setActiveProject, decisions, artifacts, fetchDecisions, fetchArtifacts, runProject, pauseProject, resumeProject, killProject } = useProjectStore();
  const { fetchConfigs } = useConfigStore();
  const { navigateTo } = useUiStore();
  const { connectProject, eventsByProject } = useEventStore();
  const [search, setSearch] = useState("");
  const [configFilter, setConfigFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const projects = projectList();
  const activeProject = projects.find((p) => p.id === activeProjectId);

  useEffect(() => {
    Promise.all([fetchProjects(), fetchConfigs()]).finally(() => setLoading(false));
  }, []);

  // Auto-select first project
  useEffect(() => {
    if (!activeProjectId && projects.length > 0) {
      const running = projects.find((p) => p.status === "running");
      setActiveProject(running?.id ?? projects[0].id);
    }
  }, [projects, activeProjectId]);

  // Fetch decisions/artifacts when selecting project
  useEffect(() => {
    if (activeProjectId) {
      fetchDecisions(activeProjectId);
      fetchArtifacts(activeProjectId);
    }
  }, [activeProjectId]);

  // Connect running projects to WS
  useEffect(() => {
    for (const p of projects) {
      if (p.status === "running") connectProject(p.id);
    }
  }, [projects]);

  // Polling for running projects
  useEffect(() => {
    const interval = setInterval(() => {
      const running = projects.filter((p) => p.status === "running");
      if (running.length > 0) fetchProjects();
    }, 3000);
    return () => clearInterval(interval);
  }, [projects]);

  const filteredProjects = useMemo(() => {
    let list = projects;
    if (configFilter) list = list.filter((p) => p.config_name === configFilter);
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) => p.prompt.toLowerCase().includes(q) || p.config_name.toLowerCase().includes(q)
      );
    }
    // Pin running projects to top
    return list.sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      return 0;
    });
  }, [projects, configFilter, search]);

  const configNames = useMemo(() => {
    const names = new Set(projects.map((p) => p.config_name));
    return Array.from(names);
  }, [projects]);

  const handleDrillIn = (project: Project) => {
    setActiveProject(project.id);
    navigateTo("project");
  };

  if (loading) {
    return (
      <div className="flex flex-1 gap-0 overflow-hidden">
        <div className="w-80 border-r border-[rgba(0,0,0,0.06)] p-4 space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
        <div className="flex-1 p-8">
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Left: Project List */}
      <aside className="w-80 shrink-0 border-r border-[rgba(0,0,0,0.06)] flex flex-col bg-[#fafafa]">
        <div className="p-3 space-y-3">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#86868b]" />
            <Input
              placeholder="Filter projects..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-8 text-[12px]"
            />
          </div>

          {/* Config filter pills */}
          {configNames.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setConfigFilter(null)}
                className={cn(
                  "px-2 py-1 rounded-full text-[11px] font-medium transition-all",
                  !configFilter
                    ? "bg-[#0071e3] text-white"
                    : "bg-[rgba(0,0,0,0.04)] text-[#6e6e73] hover:bg-[rgba(0,0,0,0.08)]"
                )}
              >
                All
              </button>
              {configNames.map((name) => (
                <button
                  key={name}
                  onClick={() => setConfigFilter(configFilter === name ? null : name)}
                  className={cn(
                    "px-2 py-1 rounded-full text-[11px] font-medium transition-all",
                    configFilter === name
                      ? "bg-[#0071e3] text-white"
                      : "bg-[rgba(0,0,0,0.04)] text-[#6e6e73] hover:bg-[rgba(0,0,0,0.08)]"
                  )}
                >
                  {name}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Project items */}
        <ScrollArea className="flex-1">
          <div className="px-2 pb-2 space-y-0.5">
            {filteredProjects.length === 0 && (
              <div className="px-3 py-12 text-center text-[13px] text-[#86868b]">
                {search ? "No matching projects" : "No projects yet"}
              </div>
            )}
            {filteredProjects.map((p) => (
              <ProjectListItem
                key={p.id}
                project={p}
                isActive={p.id === activeProjectId}
                onSelect={() => setActiveProject(p.id)}
                onDrillIn={() => handleDrillIn(p)}
              />
            ))}
          </div>
        </ScrollArea>
      </aside>

      {/* Right: Preview Panel */}
      <main className="flex-1 overflow-auto bg-[#fafafa]">
        <AnimatePresence mode="wait">
          {activeProject ? (
            <ProjectPreview
              key={activeProject.id}
              project={activeProject}
              decisions={decisions.get(activeProject.id) ?? []}
              artifacts={artifacts.get(activeProject.id) ?? []}
              events={eventsByProject.get(activeProject.id) ?? []}
              onDrillIn={() => handleDrillIn(activeProject)}
              onRun={() => runProject(activeProject.id)}
              onPause={() => pauseProject(activeProject.id)}
              onResume={() => resumeProject(activeProject.id)}
              onKill={() => killProject(activeProject.id)}
            />
          ) : (
            <EmptyState key="empty" />
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

// -- Project List Item --
function ProjectListItem({
  project,
  isActive,
  onSelect,
  onDrillIn,
}: {
  project: Project;
  isActive: boolean;
  onSelect: () => void;
  onDrillIn: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      onDoubleClick={onDrillIn}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-xl transition-all duration-150 group",
        isActive
          ? "bg-white shadow-[0_1px_3px_rgba(0,0,0,0.06)] border border-[rgba(0,0,0,0.06)]"
          : "hover:bg-white/60 border border-transparent"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-[#1d1d1f] truncate leading-tight">
            {project.prompt}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <StatusBadge status={project.status} />
            <Badge variant="neutral" size="sm">
              {project.config_name}
            </Badge>
          </div>
        </div>
        <ChevronRight
          className={cn(
            "h-4 w-4 mt-0.5 text-[#86868b] shrink-0 transition-all",
            "opacity-0 group-hover:opacity-100 -translate-x-1 group-hover:translate-x-0"
          )}
        />
      </div>
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[#86868b]">
        <span className="flex items-center gap-1">
          <Zap className="h-3 w-3" />
          {formatTokens(project.total_input_tokens + project.total_output_tokens)}
        </span>
        <span className="flex items-center gap-1">
          <DollarSign className="h-3 w-3" />
          {formatCost(project.estimated_cost)}
        </span>
        {project.created_at && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {relativeTime(project.created_at)}
          </span>
        )}
      </div>
    </button>
  );
}

// -- Project Preview Panel --
function ProjectPreview({
  project,
  decisions,
  artifacts,
  events,
  onDrillIn,
  onRun,
  onPause,
  onResume,
  onKill,
}: {
  project: Project;
  decisions: { id: string; topic: string; decision: string; confidence: number; team: string }[];
  artifacts: { id: string; name: string; type: string; team: string; status: string }[];
  events: { type: string; data: Record<string, unknown>; timestamp: string }[];
  onDrillIn: () => void;
  onRun: () => void;
  onPause: () => void;
  onResume: () => void;
  onKill: () => void;
}) {
  const recentEvents = events.slice(-8).reverse();
  const recentDecisions = decisions.slice(-5);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
      className="p-6 max-w-4xl mx-auto"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="min-w-0 flex-1">
          <h1 className="text-[20px] font-semibold text-[#1d1d1f] leading-tight mb-2">
            {project.prompt}
          </h1>
          <div className="flex items-center gap-2">
            <StatusBadge status={project.status} />
            <Badge variant="neutral" size="md">
              {project.config_name}
            </Badge>
            {project.mode && (
              <Badge variant="info" size="sm">
                {project.mode}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 ml-4">
          {project.status === "created" && (
            <Button variant="primary" size="sm" onClick={onRun}>
              <Play className="h-3.5 w-3.5" /> Run
            </Button>
          )}
          {project.status === "running" && (
            <>
              <Button variant="secondary" size="sm" onClick={onPause}>
                <Pause className="h-3.5 w-3.5" /> Pause
              </Button>
              <Button variant="destructive" size="sm" onClick={onKill}>
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            </>
          )}
          {project.status === "paused" && (
            <Button variant="primary" size="sm" onClick={onResume}>
              <Play className="h-3.5 w-3.5" /> Resume
            </Button>
          )}
          <Button variant="primary" size="sm" onClick={onDrillIn}>
            Open <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard label="Input Tokens" value={formatTokens(project.total_input_tokens)} icon={<Zap className="h-4 w-4" />} />
        <StatCard label="Output Tokens" value={formatTokens(project.total_output_tokens)} icon={<Zap className="h-4 w-4" />} />
        <StatCard label="Est. Cost" value={formatCost(project.estimated_cost)} icon={<DollarSign className="h-4 w-4" />} />
        <StatCard label="Decisions" value={String(decisions.length)} icon={<MessageSquare className="h-4 w-4" />} />
      </div>

      {/* Two-column content */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Recent Decisions */}
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-[13px] font-semibold text-[#1d1d1f] mb-3 flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-[#0071e3]" />
              Recent Decisions
            </h3>
            {recentDecisions.length === 0 ? (
              <p className="text-[12px] text-[#86868b] py-4">No decisions yet</p>
            ) : (
              <div className="space-y-2">
                {recentDecisions.map((d) => (
                  <div key={d.id} className="px-3 py-2 rounded-lg bg-[#f5f5f7] text-[12px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-[#1d1d1f]">{d.topic}</span>
                      <Badge variant={d.confidence >= 0.7 ? "success" : d.confidence >= 0.4 ? "warning" : "error"} size="sm">
                        {Math.round(d.confidence * 100)}%
                      </Badge>
                    </div>
                    <p className="text-[#6e6e73] line-clamp-2">{d.decision}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <Card>
          <CardContent className="pt-4">
            <h3 className="text-[13px] font-semibold text-[#1d1d1f] mb-3 flex items-center gap-2">
              <Clock className="h-4 w-4 text-[#0071e3]" />
              Recent Activity
            </h3>
            {recentEvents.length === 0 ? (
              <p className="text-[12px] text-[#86868b] py-4">No activity yet</p>
            ) : (
              <div className="space-y-1.5">
                {recentEvents.map((e, i) => (
                  <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[12px] hover:bg-[#f5f5f7] transition-colors">
                    <EventDot type={e.type} />
                    <span className="text-[#6e6e73] truncate flex-1">
                      {eventLabel(e)}
                    </span>
                    <span className="text-[10px] text-[#86868b] shrink-0">
                      {new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Artifacts */}
        {artifacts.length > 0 && (
          <Card className="lg:col-span-2">
            <CardContent className="pt-4">
              <h3 className="text-[13px] font-semibold text-[#1d1d1f] mb-3 flex items-center gap-2">
                <FileText className="h-4 w-4 text-[#0071e3]" />
                Artifacts ({artifacts.length})
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {artifacts.slice(0, 6).map((a) => (
                  <div key={a.id} className="px-3 py-2 rounded-lg bg-[#f5f5f7] text-[12px]">
                    <p className="font-medium text-[#1d1d1f] truncate">{a.name}</p>
                    <div className="flex items-center gap-1.5 mt-1">
                      <Badge variant="neutral" size="sm">{a.type}</Badge>
                      <span className="text-[#86868b]">{a.team}</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </motion.div>
  );
}

// -- Stat Card --
function StatCard({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[#86868b]">{icon}</span>
          <span className="text-[11px] font-medium text-[#86868b] uppercase tracking-wider">{label}</span>
        </div>
        <span className="text-[20px] font-semibold text-[#1d1d1f] tabular-nums">{value}</span>
      </CardContent>
    </Card>
  );
}

// -- Empty State --
function EmptyState() {
  const { setShowNewProject } = useUiStore();
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center justify-center h-full text-center px-8"
    >
      <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-[#0071e3]/10 to-[#5856d6]/10 flex items-center justify-center mb-4">
        <Zap className="h-8 w-8 text-[#0071e3]" />
      </div>
      <h2 className="text-[17px] font-semibold text-[#1d1d1f] mb-1">No projects yet</h2>
      <p className="text-[13px] text-[#86868b] mb-6 max-w-xs">
        Create your first project to get started with multi-agent collaboration.
      </p>
      <Button variant="primary" onClick={() => setShowNewProject(true)}>
        Create Project
      </Button>
    </motion.div>
  );
}

// -- Event helpers --
function EventDot({ type }: { type: string }) {
  const colors: Record<string, string> = {
    decision_made: "#0071e3",
    workflow_step_start: "#34c759",
    workflow_step_complete: "#34c759",
    agent_message: "#6e6e73",
    forum_gate_result: "#ff9500",
    team_round_start: "#5856d6",
    team_round_end: "#5856d6",
    artifact_created: "#af52de",
    user_input_requested: "#ff2d55",
    workflow_complete: "#34c759",
  };
  return (
    <span
      className="h-1.5 w-1.5 rounded-full shrink-0"
      style={{ backgroundColor: colors[type] ?? "#86868b" }}
    />
  );
}

function eventLabel(e: { type: string; data: Record<string, unknown> }): string {
  switch (e.type) {
    case "decision_made": return `Decision: ${e.data.topic ?? ""}`;
    case "workflow_step_start": return `Step started: ${e.data.step ?? ""}`;
    case "workflow_step_complete": return `Step completed: ${e.data.step ?? ""}`;
    case "agent_message": return `${e.data.agent ?? "Agent"}: ${String(e.data.content ?? "").slice(0, 60)}`;
    case "team_round_start": return `Round ${e.data.round ?? ""} started (${e.data.team ?? ""})`;
    case "team_round_end": return `Round ${e.data.round ?? ""} ended (${e.data.team ?? ""})`;
    case "artifact_created": return `Artifact: ${e.data.name ?? ""}`;
    case "forum_gate_result": return `Gate: ${e.data.result ?? ""}`;
    case "workflow_complete": return "Workflow completed";
    case "user_input_requested": return `Input needed: ${String(e.data.question ?? "").slice(0, 50)}`;
    default: return e.type.replace(/_/g, " ");
  }
}
