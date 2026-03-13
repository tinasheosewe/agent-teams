import { useMemo, useRef, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import {
  ChevronDown,
  ChevronRight,
  List,
  Layers,
  Gavel,
  Wrench,
  ShieldCheck,
  AlertTriangle,
  User,
  Zap,
} from "lucide-react";
import { Avatar } from "../ui/Avatar";
import { Badge } from "../ui/Badge";
import { ConfidenceRing } from "../ui/Progress";
import { cn, hashColor } from "../../lib/utils";
import type { WsEvent } from "../../stores/eventStore";

type EventFilter = "all" | "messages" | "decisions" | "tools" | "gates" | "system";

interface Props {
  events: WsEvent[];
  selectedStep: string | null;
  grouped: boolean;
  onToggleGrouped: () => void;
}

interface RoundGroup {
  team: string;
  round: number;
  events: WsEvent[];
  confidence?: number;
  startTime?: string;
  endTime?: string;
}

export function TimelineStream({ events, selectedStep, grouped, onToggleGrouped }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState<EventFilter>("all");
  const [agentFilter, setAgentFilter] = useState<Set<string>>(new Set());
  const [collapsedRounds, setCollapsedRounds] = useState<Set<string>>(new Set());

  // Extract unique agents
  const agents = useMemo(() => {
    const set = new Set<string>();
    for (const e of events) {
      if (e.data.agent && typeof e.data.agent === "string") set.add(e.data.agent);
    }
    return Array.from(set);
  }, [events]);

  // Filter events by step
  const stepFiltered = useMemo(() => {
    if (!selectedStep) return events;
    // Find events between step_start and step_complete for this step
    let inStep = false;
    const result: WsEvent[] = [];
    for (const e of events) {
      if (e.type === "workflow_step_start" && e.data.step === selectedStep) inStep = true;
      if (inStep) result.push(e);
      if (e.type === "workflow_step_complete" && e.data.step === selectedStep) inStep = false;
    }
    return result.length > 0 ? result : events.filter((e) => e.data.step === selectedStep);
  }, [events, selectedStep]);

  // Filter by type
  const typeFiltered = useMemo(() => {
    if (filter === "all") return stepFiltered;
    const typeMap: Record<EventFilter, string[]> = {
      all: [],
      messages: ["agent_message"],
      decisions: ["decision_made", "decision_superseded"],
      tools: ["agent_tool_call"],
      gates: ["forum_gate_result"],
      system: ["workflow_step_start", "workflow_step_complete", "team_round_start", "team_round_end", "team_mode_selected", "cost_update", "workflow_complete"],
    };
    const types = typeMap[filter];
    return stepFiltered.filter((e) => types.includes(e.type));
  }, [stepFiltered, filter]);

  // Filter by agent
  const filtered = useMemo(() => {
    if (agentFilter.size === 0) return typeFiltered;
    return typeFiltered.filter((e) => {
      if (e.data.agent && typeof e.data.agent === "string") return agentFilter.has(e.data.agent);
      return true; // non-agent events always shown
    });
  }, [typeFiltered, agentFilter]);

  // Group into rounds
  const roundGroups = useMemo((): RoundGroup[] => {
    if (!grouped) return [];
    const groups: RoundGroup[] = [];
    let current: RoundGroup | null = null;

    for (const e of filtered) {
      if (e.type === "team_round_start") {
        if (current) groups.push(current);
        current = {
          team: (e.data.team as string) ?? "unknown",
          round: (e.data.round as number) ?? groups.length + 1,
          events: [e],
          startTime: e.timestamp,
        };
      } else if (e.type === "team_round_end") {
        if (current) {
          current.events.push(e);
          current.endTime = e.timestamp;
          current.confidence = e.data.confidence as number | undefined;
          groups.push(current);
          current = null;
        }
      } else if (current) {
        current.events.push(e);
      } else {
        // Event outside any round
        if (groups.length === 0 || groups[groups.length - 1].round !== 0) {
          groups.push({ team: "system", round: 0, events: [e] });
        } else {
          groups[groups.length - 1].events.push(e);
        }
      }
    }
    if (current) groups.push(current);
    return groups;
  }, [filtered, grouped]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length, autoScroll]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setAutoScroll(nearBottom);
  };

  const toggleAgent = (name: string) => {
    setAgentFilter((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleRound = (key: string) => {
    setCollapsedRounds((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="shrink-0 px-4 py-2 border-b border-[rgba(0,0,0,0.06)] flex items-center gap-2 flex-wrap">
        {/* View toggle */}
        <div className="flex items-center rounded-lg bg-[#f5f5f7] p-0.5">
          <button
            onClick={() => grouped || onToggleGrouped()}
            className={cn(
              "px-2.5 py-1 rounded-md text-[11px] font-medium transition-all",
              grouped ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#86868b]"
            )}
          >
            <Layers className="h-3 w-3 inline-block mr-1" />
            Rounds
          </button>
          <button
            onClick={() => !grouped || onToggleGrouped()}
            className={cn(
              "px-2.5 py-1 rounded-md text-[11px] font-medium transition-all",
              !grouped ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#86868b]"
            )}
          >
            <List className="h-3 w-3 inline-block mr-1" />
            Flat
          </button>
        </div>

        {/* Event type filters */}
        <div className="flex items-center gap-1 ml-2">
          {(["all", "messages", "decisions", "tools", "gates", "system"] as EventFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-2 py-1 rounded-md text-[10px] font-medium transition-all capitalize",
                filter === f
                  ? "bg-[#0071e3]/10 text-[#0071e3]"
                  : "text-[#86868b] hover:text-[#6e6e73] hover:bg-[rgba(0,0,0,0.03)]"
              )}
            >
              {f}
            </button>
          ))}
        </div>

        {/* Agent chips */}
        {agents.length > 0 && (
          <div className="flex items-center gap-1 ml-auto">
            {agents.slice(0, 6).map((a) => (
              <button
                key={a}
                onClick={() => toggleAgent(a)}
                className={cn(
                  "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium transition-all",
                  agentFilter.size === 0 || agentFilter.has(a)
                    ? "opacity-100"
                    : "opacity-40"
                )}
                title={a}
              >
                <Avatar name={a} size="sm" className="h-4 w-4 text-[7px]" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Timeline content */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto px-4 py-3"
        onScroll={handleScroll}
      >
        {grouped ? (
          <RoundGroupedView
            groups={roundGroups}
            collapsedRounds={collapsedRounds}
            onToggleRound={toggleRound}
          />
        ) : (
          <FlatView events={filtered} />
        )}
        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom pill */}
      <AnimatePresence>
        {!autoScroll && (
          <motion.button
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            onClick={() => {
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
              setAutoScroll(true);
            }}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full bg-white/90 backdrop-blur-lg border border-[rgba(0,0,0,0.08)] shadow-lg text-[11px] font-medium text-[#0071e3] hover:bg-white transition-all z-10"
          >
            New events ↓
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

// -- Round Grouped View --
function RoundGroupedView({
  groups,
  collapsedRounds,
  onToggleRound,
}: {
  groups: RoundGroup[];
  collapsedRounds: Set<string>;
  onToggleRound: (key: string) => void;
}) {
  return (
    <div className="space-y-2">
      {groups.map((group, i) => {
        const key = `${group.team}-${group.round}-${i}`;
        const isCollapsed = collapsedRounds.has(key);
        const teamColor = hashColor(group.team);

        if (group.round === 0) {
          // System events outside rounds
          return (
            <div key={key} className="space-y-1">
              {group.events.map((e, j) => (
                <EventCard key={j} event={e} />
              ))}
            </div>
          );
        }

        return (
          <div key={key} className="rounded-xl border border-[rgba(0,0,0,0.06)] overflow-hidden">
            {/* Round header */}
            <button
              onClick={() => onToggleRound(key)}
              className="w-full flex items-center gap-3 px-4 py-3 bg-[#fafafa] hover:bg-[#f5f5f7] transition-colors"
            >
              {isCollapsed ? (
                <ChevronRight className="h-4 w-4 text-[#86868b] shrink-0" />
              ) : (
                <ChevronDown className="h-4 w-4 text-[#86868b] shrink-0" />
              )}
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0"
                style={{ backgroundColor: teamColor }}
              />
              <span className="text-[13px] font-semibold text-[#1d1d1f]">
                Round {group.round}
              </span>
              <span className="text-[12px] text-[#6e6e73]">{group.team}</span>
              <div className="ml-auto flex items-center gap-2">
                {group.confidence !== undefined && (
                  <ConfidenceRing value={group.confidence} size={20} strokeWidth={2} />
                )}
                {group.startTime && (
                  <span className="text-[10px] text-[#86868b]">
                    {new Date(group.startTime).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                )}
              </div>
            </button>

            {/* Round events */}
            <AnimatePresence initial={false}>
              {!isCollapsed && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
                  className="overflow-hidden"
                >
                  <div className="px-3 py-2 space-y-1 border-t border-[rgba(0,0,0,0.04)]">
                    {group.events
                      .filter((e) => e.type !== "team_round_start" && e.type !== "team_round_end")
                      .map((e, j) => (
                        <EventCard key={j} event={e} />
                      ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

// -- Flat View --
function FlatView({ events }: { events: WsEvent[] }) {
  return (
    <div className="space-y-1">
      {events.map((e, i) => (
        <EventCard key={i} event={e} />
      ))}
    </div>
  );
}

// -- Event Card --
function EventCard({ event }: { event: WsEvent }) {
  const { type, data, timestamp } = event;

  // Agent message
  if (type === "agent_message") {
    const agent = (data.agent as string) ?? "Agent";
    return (
      <div className="flex gap-3 px-3 py-2.5 rounded-xl hover:bg-[rgba(0,0,0,0.02)] transition-colors">
        <Avatar name={agent} size="sm" className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[12px] font-semibold text-[#1d1d1f]">{agent}</span>
            <span className="text-[10px] text-[#86868b]">
              {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          </div>
          <div className="text-[13px] text-[#3a3a3c] leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-code:text-[12px] prose-code:bg-[rgba(0,0,0,0.04)] prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
            <ReactMarkdown>{String(data.content ?? "")}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  // Decision
  if (type === "decision_made") {
    const conf = (data.confidence as number) ?? 0;
    return (
      <div className="px-3 py-2.5 rounded-xl bg-[#eff6ff] border border-[#bfdbfe]/50 transition-colors">
        <div className="flex items-center gap-2 mb-1">
          <Gavel className="h-3.5 w-3.5 text-[#0071e3]" />
          <span className="text-[12px] font-semibold text-[#0071e3]">Decision</span>
          <Badge
            variant={conf >= 0.7 ? "success" : conf >= 0.4 ? "warning" : "error"}
            size="sm"
          >
            {Math.round(conf * 100)}%
          </Badge>
          <span className="ml-auto text-[10px] text-[#86868b]">
            {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
        <p className="text-[13px] font-medium text-[#1d1d1f] mb-0.5">{data.topic as string}</p>
        <p className="text-[12px] text-[#6e6e73]">{data.decision as string}</p>
      </div>
    );
  }

  // Gate result
  if (type === "forum_gate_result") {
    const passed = !String(data.result ?? "").toLowerCase().includes("return");
    return (
      <div
        className={cn(
          "px-3 py-2.5 rounded-xl border transition-colors flex items-start gap-2",
          passed
            ? "bg-[#f0fdf4] border-[#bbf7d0]/50"
            : "bg-[#fef2f2] border-[#fecaca]/50"
        )}
      >
        <ShieldCheck className={cn("h-4 w-4 shrink-0 mt-0.5", passed ? "text-[#34c759]" : "text-[#ff3b30]")} />
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className={cn("text-[12px] font-semibold", passed ? "text-[#248a3d]" : "text-[#ff3b30]")}>
              Gate {passed ? "Passed" : "Returned"}
            </span>
            <span className="text-[10px] text-[#86868b]">
              {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          </div>
          {data.notes ? <p className="text-[12px] text-[#6e6e73]">{String(data.notes)}</p> : null}
        </div>
      </div>
    );
  }

  // Tool call
  if (type === "agent_tool_call") {
    return (
      <div className="px-3 py-2 rounded-xl hover:bg-[rgba(0,0,0,0.02)] transition-colors flex items-center gap-2">
        <Wrench className="h-3.5 w-3.5 text-[#86868b] shrink-0" />
        <span className="text-[11px] font-mono text-[#6e6e73] truncate">
          {data.tool as string}({data.args ? JSON.stringify(data.args).slice(0, 60) : ""})
        </span>
        <span className="text-[10px] text-[#86868b] ml-auto shrink-0">
          {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </span>
      </div>
    );
  }

  // Escalation
  if (type === "forum_escalation") {
    return (
      <div className="px-3 py-2.5 rounded-xl bg-[rgba(255,159,10,0.06)] border border-[rgba(255,159,10,0.15)] flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 text-[#ff9500] shrink-0 mt-0.5" />
        <div>
          <span className="text-[12px] font-semibold text-[#c93400]">Escalation</span>
          <p className="text-[12px] text-[#6e6e73] mt-0.5">{data.message as string}</p>
        </div>
      </div>
    );
  }

  // User input requested
  if (type === "user_input_requested") {
    return (
      <div className="px-3 py-2.5 rounded-xl bg-[rgba(0,113,227,0.06)] border border-[rgba(0,113,227,0.12)] flex items-start gap-2">
        <User className="h-4 w-4 text-[#0071e3] shrink-0 mt-0.5" />
        <div>
          <span className="text-[12px] font-semibold text-[#0071e3]">Input Needed</span>
          <p className="text-[12px] text-[#6e6e73] mt-0.5">{data.question as string}</p>
        </div>
      </div>
    );
  }

  // Workflow / step events
  if (type === "workflow_step_start" || type === "workflow_step_complete") {
    const isStart = type === "workflow_step_start";
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-[11px]">
        <div className={cn("h-2 w-2 rounded-full", isStart ? "bg-[#0071e3]" : "bg-[#34c759]")} />
        <span className="font-medium text-[#6e6e73]">
          {isStart ? "Step started" : "Step completed"}: <span className="text-[#1d1d1f]">{data.step as string}</span>
        </span>
        <span className="text-[10px] text-[#86868b] ml-auto">
          {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    );
  }

  // Round start/end
  if (type === "team_round_start" || type === "team_round_end") {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-[11px]">
        <div
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: hashColor((data.team as string) ?? "team") }}
        />
        <span className="text-[#86868b]">
          {type === "team_round_start" ? "Round started" : "Round ended"} · {data.team as string} · Round {data.round as number}
        </span>
      </div>
    );
  }

  // Workflow complete
  if (type === "workflow_complete") {
    return (
      <div className="px-3 py-3 rounded-xl bg-gradient-to-r from-[#f0fdf4] to-[#eff6ff] border border-[#bbf7d0]/50 text-center">
        <div className="flex items-center justify-center gap-2">
          <Zap className="h-4 w-4 text-[#34c759]" />
          <span className="text-[13px] font-semibold text-[#248a3d]">Workflow Complete</span>
        </div>
      </div>
    );
  }

  // Generic / cost_update / etc
  if (type === "cost_update") return null; // hide noise
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-[11px] text-[#86868b]">
      <span className="h-1.5 w-1.5 rounded-full bg-[#86868b]" />
      <span>{type.replace(/_/g, " ")}</span>
    </div>
  );
}
