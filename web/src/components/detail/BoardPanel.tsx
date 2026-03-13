/**
 * BoardPanel — bulletin-board visualization of the deliberation state.
 *
 * Three-column kanban layout (Consensus | Open | Contested) with point cards
 * showing claims, author avatars, reaction tallies, and click-to-expand
 * history (version timeline, full reaction reasoning).
 *
 * Builds the board live from agent_message events during active deliberation,
 * then switches to the authoritative snapshot from deliberation_complete.
 */

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  GitBranch,
  CircleDot,
  Pin,
  Users,
  ArrowRight,
} from "lucide-react";
import { Badge } from "../ui/Badge";
import { Avatar } from "../ui/Avatar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/Tooltip";
import { cn } from "../../lib/utils";
import type { WsEvent } from "../../stores/eventStore";

// ── Types ────────────────────────────────────────────────────

type PointStatus = "consensus" | "contested" | "open";
type Stance = "agree" | "disagree" | "question";

interface BoardReaction {
  agent: string;
  stance: Stance;
  reasoning: string;
}

interface PointVersionData {
  version: number;
  claim: string;
  amended_by: string;
  amendment_reason?: string | null;
  reactions: BoardReaction[];
}

interface BoardPoint {
  id: number;
  claim: string;
  author: string;
  version: number;
  status: PointStatus;
  reactions: BoardReaction[];
  versions?: PointVersionData[];
}

interface BoardState {
  task: string;
  agents: string[];
  phase: string;
  points: BoardPoint[];
  turnNumber: number;
  converged: boolean;
  settled: boolean;
  summary?: string;
  verdict?: string | null;
  mode_selection?: string | null;
  totalPoints: number;
  consensusCount: number;
  contestedCount: number;
  openCount: number;
}

interface Props {
  events: WsEvent[];
}

// ── Board state builder ──────────────────────────────────────

function computePointStatus(
  point: { author: string; reactions: BoardReaction[] },
  roster: string[],
): PointStatus {
  const others = roster.filter((a) => a !== point.author);
  if (others.length === 0) return "consensus";
  if (point.reactions.some((r) => r.stance === "disagree")) return "contested";
  const reacted = new Set(point.reactions.map((r) => r.agent));
  if (others.every((a) => reacted.has(a))) return "consensus";
  return "open";
}

function useBoardState(events: WsEvent[]): BoardState | null {
  return useMemo(() => {
    // First check for deliberation_complete snapshots (authoritative)
    const completeEvents = events.filter(
      (e) => e.type === "deliberation_complete" && Array.isArray(e.data.board),
    );
    const startEvents = events.filter((e) => e.type === "deliberation_start");
    const cycleEvents = events.filter((e) => e.type === "deliberation_cycle");

    const lastStart = startEvents[startEvents.length - 1];
    const lastCycle = cycleEvents[cycleEvents.length - 1];
    const lastComplete = completeEvents[completeEvents.length - 1];

    if (lastComplete) {
      const d = lastComplete.data;
      return {
        task: lastStart?.data.task as string ?? "",
        agents: (lastStart?.data.agents as string[]) ?? [],
        phase: d.phase as string,
        points: (d.board as BoardPoint[]) ?? [],
        turnNumber: lastCycle?.data.round as number ?? 0,
        converged: true,
        settled: true,
        summary: d.summary as string | undefined,
        verdict: d.verdict as string | null,
        mode_selection: d.mode_selection as string | null,
        totalPoints: d.total_points as number,
        consensusCount: d.consensus_points as number,
        contestedCount: d.contested_points as number,
        openCount: (d.total_points as number) - (d.consensus_points as number) - (d.contested_points as number),
      };
    }

    // Build live board from agent_message events with board_actions
    if (!lastStart) return null;

    const roster = (lastStart.data.agents as string[]) ?? [];
    const task = (lastStart.data.task as string) ?? "";
    const phase = (lastStart.data.phase as string) ?? "";

    // Find agent_message events after the last start
    const startIdx = events.indexOf(lastStart);
    const liveMessages = events
      .slice(startIdx)
      .filter((e) => e.type === "agent_message" && e.data.board_actions);

    if (liveMessages.length === 0 && cycleEvents.length === 0) return null;

    // Assemble board from actions
    const pointMap = new Map<number, {
      id: number;
      claim: string;
      author: string;
      version: number;
      reactions: Map<string, BoardReaction>;
      versions: PointVersionData[];
    }>();
    let nextId = 1;

    for (const msg of liveMessages) {
      const agent = msg.data.agent as string;
      const actions = msg.data.board_actions as {
        new_points?: { id: number; claim: string }[];
        reactions?: { point_id: number; stance: string; reasoning: string }[];
        amendments?: { point_id: number; new_claim: string; reason: string }[];
      };

      for (const np of actions.new_points ?? []) {
        const id = np.id || nextId++;
        if (id >= nextId) nextId = id + 1;
        pointMap.set(id, {
          id,
          claim: np.claim,
          author: agent,
          version: 1,
          reactions: new Map(),
          versions: [{ version: 1, claim: np.claim, amended_by: agent, reactions: [] }],
        });
      }

      for (const rxn of actions.reactions ?? []) {
        const point = pointMap.get(rxn.point_id);
        if (point) {
          const reaction: BoardReaction = {
            agent,
            stance: rxn.stance as Stance,
            reasoning: rxn.reasoning,
          };
          point.reactions.set(agent, reaction);
          // Also add to current version's reactions
          const curVer = point.versions[point.versions.length - 1];
          const existingIdx = curVer.reactions.findIndex((r) => r.agent === agent);
          if (existingIdx >= 0) curVer.reactions[existingIdx] = reaction;
          else curVer.reactions.push(reaction);
        }
      }

      for (const amd of actions.amendments ?? []) {
        const point = pointMap.get(amd.point_id);
        if (point) {
          point.version += 1;
          point.claim = amd.new_claim;
          point.reactions.clear();
          point.versions.push({
            version: point.version,
            claim: amd.new_claim,
            amended_by: agent,
            amendment_reason: amd.reason,
            reactions: [],
          });
        }
      }
    }

    // Convert to BoardPoint array
    const points: BoardPoint[] = Array.from(pointMap.values()).map((p) => ({
      id: p.id,
      claim: p.claim,
      author: p.author,
      version: p.version,
      status: computePointStatus(
        { author: p.author, reactions: Array.from(p.reactions.values()) },
        roster,
      ),
      reactions: Array.from(p.reactions.values()),
      versions: p.versions,
    }));

    const consensusCount = points.filter((p) => p.status === "consensus").length;
    const contestedCount = points.filter((p) => p.status === "contested").length;
    const openCount = points.filter((p) => p.status === "open").length;

    return {
      task,
      agents: roster,
      phase,
      points,
      turnNumber: (lastCycle?.data.round as number) ?? liveMessages.length,
      converged: (lastCycle?.data.converged as boolean) ?? false,
      settled: (lastCycle?.data.board_settled as boolean) ?? false,
      totalPoints: points.length,
      consensusCount,
      contestedCount,
      openCount,
    };
  }, [events]);
}

// ── Main component ───────────────────────────────────────────

export function BoardPanel({ events }: Props) {
  const board = useBoardState(events);

  if (!board) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <Pin className="h-10 w-10 text-[#d1d1d6] mx-auto mb-3" />
          <p className="text-[14px] font-medium text-[#86868b]">No deliberation yet</p>
          <p className="text-[12px] text-[#aeaeb2] mt-1">
            Points will appear here as agents discuss
          </p>
        </div>
      </div>
    );
  }

  const columns: { status: PointStatus; label: string; color: string; bgColor: string; borderColor: string }[] = [
    { status: "consensus", label: "Consensus", color: "#34c759", bgColor: "bg-[#f0fdf4]", borderColor: "border-[#bbf7d0]" },
    { status: "open", label: "Open", color: "#0071e3", bgColor: "bg-[#eff6ff]", borderColor: "border-[#bfdbfe]" },
    { status: "contested", label: "Contested", color: "#ff9500", bgColor: "bg-[#fffbeb]", borderColor: "border-[#fde68a]" },
  ];

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex flex-col h-full bg-[#fafafa]">
        {/* Board header */}
        <div className="shrink-0 px-5 py-3 bg-white border-b border-[rgba(0,0,0,0.06)]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Pin className="h-4 w-4 text-[#0071e3]" />
              <h2 className="text-[14px] font-semibold text-[#1d1d1f] capitalize">
                {board.phase} Board
              </h2>
              {board.converged ? (
                <Badge variant="success" size="sm">Converged</Badge>
              ) : (
                <Badge variant="info" size="sm">Turn {board.turnNumber}</Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              {board.agents.length > 0 && (
                <div className="flex items-center gap-1">
                  <Users className="h-3 w-3 text-[#86868b]" />
                  <div className="flex -space-x-1.5">
                    {board.agents.map((a) => (
                      <Tooltip key={a}>
                        <TooltipTrigger asChild>
                          <div><Avatar name={a} size="sm" className="h-5 w-5 text-[8px] ring-2 ring-white" /></div>
                        </TooltipTrigger>
                        <TooltipContent>{a}</TooltipContent>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          {board.task && (
            <p className="text-[12px] text-[#6e6e73] line-clamp-2">{board.task}</p>
          )}
          {/* Stat pills */}
          <div className="flex items-center gap-3 mt-2">
            {columns.map((col) => {
              const count = board.points.filter((p) => p.status === col.status).length;
              return (
                <span key={col.status} className="flex items-center gap-1.5 text-[11px]">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: col.color }}
                  />
                  <span className="font-medium text-[#1d1d1f]">{count}</span>
                  <span className="text-[#86868b]">{col.label.toLowerCase()}</span>
                </span>
              );
            })}
            <span className="text-[11px] text-[#aeaeb2] ml-auto">
              {board.totalPoints} point{board.totalPoints !== 1 ? "s" : ""}
            </span>
          </div>
        </div>

        {/* Column layout */}
        <div className="flex-1 overflow-auto">
          <div className="grid grid-cols-3 gap-0 h-full min-h-0">
            {columns.map((col) => {
              const colPoints = board.points.filter((p) => p.status === col.status);
              return (
                <StatusColumn
                  key={col.status}
                  label={col.label}
                  color={col.color}
                  bgColor={col.bgColor}
                  borderColor={col.borderColor}
                  points={colPoints}
                  agents={board.agents}
                />
              );
            })}
          </div>
        </div>

        {/* Synthesis footer */}
        {board.summary && (
          <div className="shrink-0 px-5 py-3 border-t border-[rgba(0,0,0,0.06)] bg-white">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] font-semibold text-[#0071e3] uppercase tracking-wider">
                Synthesis
              </span>
              {board.verdict && (
                <Badge variant={board.verdict === "accept" ? "success" : "warning"} size="sm">
                  {board.verdict}
                </Badge>
              )}
              {board.mode_selection && (
                <Badge variant="info" size="sm">{board.mode_selection}</Badge>
              )}
            </div>
            <p className="text-[12px] text-[#1d1d1f] leading-relaxed">{board.summary}</p>
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

// ── Status column ────────────────────────────────────────────

function StatusColumn({
  label,
  color,
  bgColor,
  borderColor,
  points,
  agents,
}: {
  label: string;
  color: string;
  bgColor: string;
  borderColor: string;
  points: BoardPoint[];
  agents: string[];
}) {
  return (
    <div className={cn("flex flex-col border-r border-[rgba(0,0,0,0.06)] last:border-r-0 min-h-0")}>
      {/* Column header */}
      <div className={cn("shrink-0 px-3 py-2.5 border-b", borderColor, bgColor)}>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
          <span className="text-[12px] font-semibold text-[#1d1d1f]">{label}</span>
          <span className="text-[11px] text-[#86868b] ml-auto">{points.length}</span>
        </div>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {points.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <span className="text-[11px] text-[#aeaeb2]">No points</span>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {points.map((point) => (
              <motion.div
                key={point.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
              >
                <PointCard point={point} agents={agents} />
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
}

// ── Point card ───────────────────────────────────────────────

function PointCard({ point, agents }: { point: BoardPoint; agents: string[] }) {
  const [expanded, setExpanded] = useState(false);

  const statusAccent = {
    consensus: "#34c759",
    contested: "#ff9500",
    open: "#0071e3",
  }[point.status];

  return (
    <div
      className={cn(
        "rounded-lg bg-white border border-[rgba(0,0,0,0.08)] overflow-hidden",
        "shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover:shadow-[0_2px_8px_rgba(0,0,0,0.08)]",
        "transition-shadow cursor-pointer",
      )}
      onClick={() => setExpanded(!expanded)}
    >
      {/* Colored top edge */}
      <div className="h-[3px]" style={{ backgroundColor: statusAccent }} />

      <div className="px-3 py-2.5">
        {/* Point header */}
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="text-[10px] font-mono font-medium text-[#86868b]">#{point.id}</span>
          <Avatar name={point.author} size="sm" className="h-4 w-4 text-[7px]" />
          <span className="text-[10px] text-[#6e6e73] truncate">{point.author}</span>
          {point.version > 1 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex items-center gap-0.5 text-[9px] text-[#af52de] font-medium ml-auto">
                  <GitBranch className="h-2.5 w-2.5" />v{point.version}
                </span>
              </TooltipTrigger>
              <TooltipContent>Amended {point.version - 1} time{point.version > 2 ? "s" : ""}</TooltipContent>
            </Tooltip>
          )}
          {expanded ? (
            <ChevronDown className="h-3 w-3 text-[#aeaeb2] ml-auto shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-[#aeaeb2] ml-auto shrink-0" />
          )}
        </div>

        {/* Claim text */}
        <p className={cn(
          "text-[12px] text-[#1d1d1f] leading-snug",
          !expanded && "line-clamp-3",
        )}>
          {point.claim}
        </p>

        {/* Reaction avatars — always visible */}
        {point.reactions.length > 0 && (
          <div className="flex items-center gap-1 mt-2 flex-wrap">
            {point.reactions.map((r) => (
              <Tooltip key={r.agent}>
                <TooltipTrigger asChild>
                  <div
                    className={cn(
                      "rounded-full p-[2px]",
                      r.stance === "agree" && "bg-[#34c759]/20",
                      r.stance === "disagree" && "bg-[#ff3b30]/20",
                      r.stance === "question" && "bg-[#ff9500]/20",
                    )}
                  >
                    <Avatar name={r.agent} size="sm" className="h-4 w-4 text-[7px]" />
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <span className="font-medium">{r.agent}</span>
                  {" — "}
                  <span className={cn(
                    r.stance === "agree" && "text-[#34c759]",
                    r.stance === "disagree" && "text-[#ff3b30]",
                    r.stance === "question" && "text-[#ff9500]",
                  )}>
                    {r.stance}
                  </span>
                </TooltipContent>
              </Tooltip>
            ))}
            {/* Tally */}
            <ReactionTally reactions={point.reactions} />
          </div>
        )}
      </div>

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="border-t border-[rgba(0,0,0,0.06)] px-3 py-2.5 space-y-3 bg-[#fafafa]">
              {/* Version history */}
              {point.versions && point.versions.length > 1 && (
                <VersionHistory versions={point.versions} />
              )}

              {/* Full reactions */}
              {point.reactions.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold text-[#86868b] uppercase tracking-wider mb-1.5">
                    Reactions
                  </h4>
                  <div className="space-y-1.5">
                    {point.reactions.map((r) => (
                      <ReactionDetail key={r.agent} reaction={r} />
                    ))}
                  </div>
                </div>
              )}

              {/* Unreacted agents */}
              {(() => {
                const reacted = new Set(point.reactions.map((r) => r.agent));
                const unreacted = agents.filter(
                  (a) => a !== point.author && !reacted.has(a),
                );
                if (unreacted.length === 0) return null;
                return (
                  <div className="flex items-center gap-1.5 text-[10px] text-[#aeaeb2]">
                    <CircleDot className="h-3 w-3" />
                    <span>Awaiting: {unreacted.join(", ")}</span>
                  </div>
                );
              })()}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Version history ──────────────────────────────────────────

function VersionHistory({ versions }: { versions: PointVersionData[] }) {
  const [showAll, setShowAll] = useState(false);
  const displayed = showAll ? versions : versions.slice(-2);

  return (
    <div>
      <h4 className="text-[10px] font-semibold text-[#86868b] uppercase tracking-wider mb-1.5">
        History
      </h4>
      <div className="relative pl-3">
        {/* Vertical line */}
        <div className="absolute left-[5px] top-1 bottom-1 w-px bg-[#d1d1d6]" />

        {!showAll && versions.length > 2 && (
          <button
            onClick={() => setShowAll(true)}
            className="text-[10px] text-[#0071e3] mb-1.5 hover:underline"
          >
            Show {versions.length - 2} earlier version{versions.length > 3 ? "s" : ""}
          </button>
        )}

        {displayed.map((v) => {
          const isLatest = v.version === versions[versions.length - 1].version;
          return (
            <div key={v.version} className="relative mb-2 last:mb-0">
              {/* Dot */}
              <div
                className={cn(
                  "absolute left-[-8px] top-1 h-2 w-2 rounded-full border-2 border-white",
                  isLatest ? "bg-[#0071e3]" : "bg-[#d1d1d6]",
                )}
              />
              <div className="pl-2">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className={cn(
                    "text-[10px] font-medium",
                    isLatest ? "text-[#0071e3]" : "text-[#aeaeb2]",
                  )}>
                    v{v.version}
                  </span>
                  {v.amended_by && v.version > 1 && (
                    <span className="text-[10px] text-[#86868b]">by {v.amended_by}</span>
                  )}
                </div>
                <p className={cn(
                  "text-[11px] leading-snug",
                  isLatest ? "text-[#1d1d1f]" : "text-[#aeaeb2] line-through",
                )}>
                  {v.claim}
                </p>
                {v.amendment_reason && (
                  <p className="text-[10px] text-[#86868b] italic mt-0.5">
                    <ArrowRight className="h-2.5 w-2.5 inline mr-0.5" />
                    {v.amendment_reason}
                  </p>
                )}
                {/* Reactions on older versions (collapsed) */}
                {!isLatest && v.reactions.length > 0 && (
                  <div className="flex items-center gap-1 mt-1 opacity-50">
                    {v.reactions.map((r) => {
                      const Icon =
                        r.stance === "agree" ? CheckCircle2 :
                        r.stance === "disagree" ? XCircle : HelpCircle;
                      const color =
                        r.stance === "agree" ? "text-[#34c759]" :
                        r.stance === "disagree" ? "text-[#ff3b30]" : "text-[#ff9500]";
                      return (
                        <span key={r.agent} className="flex items-center gap-0.5">
                          <Icon className={cn("h-2.5 w-2.5", color)} />
                          <span className="text-[9px] text-[#aeaeb2]">{r.agent}</span>
                        </span>
                      );
                    })}
                    <span className="text-[9px] text-[#d1d1d6]">(superseded)</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Reaction components ──────────────────────────────────────

function ReactionTally({ reactions }: { reactions: BoardReaction[] }) {
  const agrees = reactions.filter((r) => r.stance === "agree").length;
  const disagrees = reactions.filter((r) => r.stance === "disagree").length;
  const questions = reactions.filter((r) => r.stance === "question").length;

  return (
    <span className="flex items-center gap-1.5 ml-auto text-[10px] font-medium">
      {agrees > 0 && (
        <span className="flex items-center gap-0.5 text-[#34c759]">
          <CheckCircle2 className="h-3 w-3" />{agrees}
        </span>
      )}
      {disagrees > 0 && (
        <span className="flex items-center gap-0.5 text-[#ff3b30]">
          <XCircle className="h-3 w-3" />{disagrees}
        </span>
      )}
      {questions > 0 && (
        <span className="flex items-center gap-0.5 text-[#ff9500]">
          <HelpCircle className="h-3 w-3" />{questions}
        </span>
      )}
    </span>
  );
}

function ReactionDetail({ reaction }: { reaction: BoardReaction }) {
  const config = {
    agree: { icon: CheckCircle2, color: "text-[#34c759]", bg: "bg-[#34c759]/8", label: "agrees" },
    disagree: { icon: XCircle, color: "text-[#ff3b30]", bg: "bg-[#ff3b30]/8", label: "disagrees" },
    question: { icon: HelpCircle, color: "text-[#ff9500]", bg: "bg-[#ff9500]/8", label: "questions" },
  }[reaction.stance];
  const Icon = config.icon;

  return (
    <div className={cn("flex items-start gap-2 px-2 py-1.5 rounded-lg", config.bg)}>
      <Icon className={cn("h-3.5 w-3.5 shrink-0 mt-0.5", config.color)} />
      <Avatar name={reaction.agent} size="sm" className="h-4 w-4 text-[7px] shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1">
        <span className="text-[11px] font-medium text-[#1d1d1f]">{reaction.agent}</span>
        <span className={cn("text-[10px] ml-1", config.color)}>{config.label}</span>
        <p className="text-[11px] text-[#6e6e73] leading-snug mt-0.5">{reaction.reasoning}</p>
      </div>
    </div>
  );
}
