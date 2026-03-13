/**
 * BoardPanel — renders the deliberation board state from events.
 *
 * Consumes `deliberation_complete` events to show the final board snapshot
 * (points, statuses, reactions, version info) and `deliberation_cycle`
 * events to show convergence progress.
 */

import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  MessageCircle,
  ArrowUpDown,
  CircleDot,
} from "lucide-react";
import { Badge } from "../ui/Badge";
import { Avatar } from "../ui/Avatar";
import { cn } from "../../lib/utils";
import type { WsEvent } from "../../stores/eventStore";

// Mirrors backend PointStatus
type PointStatus = "consensus" | "contested" | "open";

interface BoardReaction {
  agent: string;
  stance: "agree" | "disagree" | "question";
  reasoning: string;
}

interface BoardPoint {
  id: number;
  claim: string;
  author: string;
  version: number;
  status: PointStatus;
  reactions: BoardReaction[];
}

interface BoardSnapshot {
  phase: string;
  summary: string;
  verdict?: string | null;
  mode_selection?: string | null;
  total_points: number;
  consensus_points: number;
  contested_points: number;
  board: BoardPoint[];
}

interface Props {
  events: WsEvent[];
}

export function BoardPanel({ events }: Props) {
  // Extract all board snapshots from deliberation_complete events
  const snapshots = useMemo(() => {
    const result: BoardSnapshot[] = [];
    for (const e of events) {
      if (e.type === "deliberation_complete" && Array.isArray(e.data.board)) {
        result.push(e.data as unknown as BoardSnapshot);
      }
    }
    return result;
  }, [events]);

  // Extract convergence timeline from deliberation_cycle events
  const cycles = useMemo(() => {
    return events
      .filter((e) => e.type === "deliberation_cycle")
      .map((e) => ({
        turn: e.data.round as number,
        converged: e.data.converged as boolean,
        phase: e.data.phase as string,
        doneAgents: e.data.done_agents as number | undefined,
        totalAgents: e.data.total_agents as number | undefined,
        settled: e.data.board_settled as boolean | undefined,
        timestamp: e.timestamp,
      }));
  }, [events]);

  // Extract start events for agent list
  const phases = useMemo(() => {
    return events
      .filter((e) => e.type === "deliberation_start")
      .map((e) => ({
        phase: e.data.phase as string,
        agents: e.data.agents as string[],
        task: e.data.task as string,
      }));
  }, [events]);

  if (snapshots.length === 0 && cycles.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-4">
      {/* Phase summaries */}
      {phases.map((p, i) => (
        <div key={i} className="px-3 py-2 rounded-lg bg-[#f5f5f7]">
          <div className="flex items-center gap-2 mb-1">
            <CircleDot className="h-3 w-3 text-[#0071e3]" />
            <span className="text-[11px] font-semibold text-[#1d1d1f] capitalize">
              {p.phase} phase
            </span>
            <span className="text-[10px] text-[#86868b]">
              {p.agents.length} agent{p.agents.length !== 1 ? "s" : ""}
            </span>
          </div>
          <div className="flex gap-1 flex-wrap">
            {p.agents.map((a) => (
              <div key={a} className="flex items-center gap-1">
                <Avatar name={a} size="sm" className="h-4 w-4 text-[7px]" />
                <span className="text-[10px] text-[#6e6e73]">{a}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* Convergence progress */}
      {cycles.length > 0 && <ConvergenceTimeline cycles={cycles} />}

      {/* Board snapshots */}
      {snapshots.map((snap, i) => (
        <BoardSnapshotView key={i} snapshot={snap} index={i} total={snapshots.length} />
      ))}
    </div>
  );
}

// ── Convergence timeline ─────────────────────────────────────

interface CycleInfo {
  turn: number;
  converged: boolean;
  phase: string;
  doneAgents?: number;
  totalAgents?: number;
  settled?: boolean;
  timestamp: string;
}

function ConvergenceTimeline({ cycles }: { cycles: CycleInfo[] }) {
  const last = cycles[cycles.length - 1];
  const hasAgentInfo = last?.doneAgents !== undefined && last?.totalAgents !== undefined;

  return (
    <div className="px-3 py-2 rounded-lg border border-[rgba(0,0,0,0.06)]">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-[#86868b] uppercase tracking-wider">
          Convergence
        </span>
        <span className="text-[10px] text-[#86868b]">
          {cycles.length} turn{cycles.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Progress dots */}
      <div className="flex items-center gap-0.5 mb-2 flex-wrap">
        {cycles.map((c, i) => (
          <div
            key={i}
            title={`Turn ${c.turn}: ${c.converged ? "converged" : "in progress"}`}
            className={cn(
              "h-2 w-2 rounded-full transition-colors",
              c.converged
                ? "bg-[#34c759]"
                : c.settled
                  ? "bg-[#ff9500]"
                  : "bg-[#0071e3]/40"
            )}
          />
        ))}
      </div>

      {/* Status summary */}
      {hasAgentInfo && (
        <div className="flex items-center gap-3 text-[10px] text-[#6e6e73]">
          <span>
            {last.doneAgents}/{last.totalAgents} agents done
          </span>
          {last.settled !== undefined && (
            <span className={last.settled ? "text-[#34c759]" : "text-[#ff9500]"}>
              {last.settled ? "board settled" : "open points remain"}
            </span>
          )}
          {last.converged && (
            <Badge variant="success" size="sm">converged</Badge>
          )}
        </div>
      )}
    </div>
  );
}

// ── Board snapshot ───────────────────────────────────────────

function BoardSnapshotView({
  snapshot,
  index,
  total,
}: {
  snapshot: BoardSnapshot;
  index: number;
  total: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const label = total > 1
    ? `${snapshot.phase} board (${index + 1}/${total})`
    : `${snapshot.phase} board`;

  return (
    <div className="rounded-xl border border-[rgba(0,0,0,0.06)] overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-3 bg-[#fafafa] hover:bg-[#f5f5f7] transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-[#86868b]" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-[#86868b]" />
        )}
        <MessageCircle className="h-3.5 w-3.5 text-[#0071e3]" />
        <span className="text-[12px] font-semibold text-[#1d1d1f] capitalize">{label}</span>
        <div className="ml-auto flex items-center gap-2">
          <StatPill
            count={snapshot.consensus_points}
            variant="success"
            label="consensus"
          />
          {snapshot.contested_points > 0 && (
            <StatPill
              count={snapshot.contested_points}
              variant="warning"
              label="contested"
            />
          )}
          {snapshot.total_points - snapshot.consensus_points - snapshot.contested_points > 0 && (
            <StatPill
              count={snapshot.total_points - snapshot.consensus_points - snapshot.contested_points}
              variant="neutral"
              label="open"
            />
          )}
        </div>
      </button>

      {/* Points */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
          >
            <div className="px-3 py-2 space-y-2 border-t border-[rgba(0,0,0,0.04)]">
              {snapshot.board.map((point) => (
                <PointCard key={point.id} point={point} />
              ))}

              {/* Synthesis summary */}
              {snapshot.summary && (
                <div className="px-3 py-2 rounded-lg bg-[#eff6ff] border border-[#bfdbfe]/50 mt-2">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-semibold text-[#0071e3] uppercase tracking-wider">
                      Synthesis
                    </span>
                    {snapshot.verdict && (
                      <Badge
                        variant={snapshot.verdict === "accept" ? "success" : "warning"}
                        size="sm"
                      >
                        {snapshot.verdict}
                      </Badge>
                    )}
                    {snapshot.mode_selection && (
                      <Badge variant="info" size="sm">{snapshot.mode_selection}</Badge>
                    )}
                  </div>
                  <p className="text-[11px] text-[#1d1d1f]">{snapshot.summary}</p>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Point card ───────────────────────────────────────────────

function PointCard({ point }: { point: BoardPoint }) {
  const [showReactions, setShowReactions] = useState(false);
  const statusConfig = {
    consensus: { bg: "bg-[#f0fdf4]", border: "border-[#bbf7d0]/50", icon: CheckCircle2, color: "text-[#34c759]", label: "Consensus" },
    contested: { bg: "bg-[#fffbeb]", border: "border-[#fde68a]/50", icon: XCircle, color: "text-[#ff9500]", label: "Contested" },
    open: { bg: "bg-white", border: "border-[rgba(0,0,0,0.06)]", icon: CircleDot, color: "text-[#86868b]", label: "Open" },
  };
  const cfg = statusConfig[point.status] || statusConfig.open;
  const StatusIcon = cfg.icon;

  return (
    <div className={cn("rounded-lg border px-3 py-2", cfg.bg, cfg.border)}>
      <div className="flex items-start gap-2">
        <StatusIcon className={cn("h-3.5 w-3.5 shrink-0 mt-0.5", cfg.color)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[10px] font-medium text-[#86868b]">
              #{point.id}
            </span>
            <Avatar name={point.author} size="sm" className="h-4 w-4 text-[7px]" />
            <span className="text-[10px] text-[#6e6e73]">{point.author}</span>
            {point.version > 1 && (
              <span className="flex items-center gap-0.5 text-[9px] text-[#af52de]">
                <ArrowUpDown className="h-2.5 w-2.5" /> v{point.version}
              </span>
            )}
          </div>
          <p className="text-[12px] text-[#1d1d1f] leading-snug">{point.claim}</p>

          {/* Reactions */}
          {point.reactions.length > 0 && (
            <button
              onClick={() => setShowReactions(!showReactions)}
              className="mt-1.5 flex items-center gap-1 text-[10px] text-[#86868b] hover:text-[#6e6e73] transition-colors"
            >
              <ReactionSummary reactions={point.reactions} />
              {showReactions ? (
                <ChevronDown className="h-2.5 w-2.5" />
              ) : (
                <ChevronRight className="h-2.5 w-2.5" />
              )}
            </button>
          )}
          <AnimatePresence>
            {showReactions && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-1.5 space-y-1">
                  {point.reactions.map((r, i) => (
                    <ReactionRow key={i} reaction={r} />
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

// ── Reaction components ──────────────────────────────────────

function ReactionSummary({ reactions }: { reactions: BoardReaction[] }) {
  const agrees = reactions.filter((r) => r.stance === "agree").length;
  const disagrees = reactions.filter((r) => r.stance === "disagree").length;
  const questions = reactions.filter((r) => r.stance === "question").length;

  return (
    <span className="flex items-center gap-1.5">
      {agrees > 0 && <span className="text-[#34c759]">+{agrees}</span>}
      {disagrees > 0 && <span className="text-[#ff3b30]">-{disagrees}</span>}
      {questions > 0 && <span className="text-[#ff9500]">?{questions}</span>}
    </span>
  );
}

function ReactionRow({ reaction }: { reaction: BoardReaction }) {
  const stanceConfig = {
    agree: { icon: CheckCircle2, color: "text-[#34c759]" },
    disagree: { icon: XCircle, color: "text-[#ff3b30]" },
    question: { icon: HelpCircle, color: "text-[#ff9500]" },
  };
  const cfg = stanceConfig[reaction.stance];
  const Icon = cfg.icon;

  return (
    <div className="flex items-start gap-1.5 pl-1">
      <Icon className={cn("h-3 w-3 shrink-0 mt-0.5", cfg.color)} />
      <Avatar name={reaction.agent} size="sm" className="h-3.5 w-3.5 text-[6px] shrink-0 mt-0.5" />
      <div className="min-w-0">
        <span className="text-[10px] font-medium text-[#1d1d1f]">{reaction.agent}</span>
        <span className="text-[10px] text-[#6e6e73] ml-1">{reaction.reasoning}</span>
      </div>
    </div>
  );
}

// ── Stat pill ────────────────────────────────────────────────

function StatPill({
  count,
  variant,
  label,
}: {
  count: number;
  variant: "success" | "warning" | "neutral";
  label: string;
}) {
  const colors = {
    success: "bg-[#f0fdf4] text-[#248a3d]",
    warning: "bg-[#fffbeb] text-[#c93400]",
    neutral: "bg-[#f5f5f7] text-[#86868b]",
  };
  return (
    <span
      className={cn("px-1.5 py-0.5 rounded-full text-[9px] font-medium", colors[variant])}
      title={label}
    >
      {count} {label}
    </span>
  );
}

// ── Empty state ──────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="py-8 text-center">
      <MessageCircle className="h-6 w-6 text-[#86868b] mx-auto mb-2 opacity-40" />
      <p className="text-[12px] text-[#86868b]">No deliberation data yet</p>
      <p className="text-[10px] text-[#aeaeb2] mt-0.5">
        Board state appears after agents deliberate
      </p>
    </div>
  );
}
