import { useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  MessageSquare,
  FileText,
  ShieldCheck,
  Scroll,
  Layers,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  Search,
  AlertTriangle,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/Tabs";
import { Badge, StatusBadge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Avatar } from "../ui/Avatar";
import { Progress, ConfidenceRing } from "../ui/Progress";
import { Input } from "../ui/Input";
import { ScrollArea } from "../ui/ScrollArea";
import { cn, hashColor } from "../../lib/utils";
import type { WsEvent } from "../../stores/eventStore";
import type { Decision, Artifact, DiscussionSummary } from "../../api";
import * as api from "../../api";
import { BoardPanel } from "./BoardPanel";

interface Props {
  projectId: string;
  selectedStep: string | null;
  events: WsEvent[];
  decisions: Decision[];
  artifacts: Artifact[];
  open: boolean;
  onClose: () => void;
  onVeto: (decisionId: string) => void;
}

interface StepInfo {
  team?: string;
  mode?: string;
  rounds: number;
  duration?: number;
  confidence?: number;
  gateResult?: string;
  gateNotes?: string;
  attempts: number;
}

export function ContextPanel({
  projectId,
  selectedStep,
  events,
  decisions,
  artifacts,
  open,
  onClose,
  onVeto,
}: Props) {
  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.aside
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 40, opacity: 0 }}
        transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
        className="w-[380px] shrink-0 border-l border-[rgba(0,0,0,0.06)] bg-white flex flex-col overflow-hidden"
      >
        {selectedStep ? (
          <StepDetail
            projectId={projectId}
            step={selectedStep}
            events={events}
            decisions={decisions}
            artifacts={artifacts}
            onClose={onClose}
            onVeto={onVeto}
          />
        ) : (
          <ProjectSummary
            projectId={projectId}
            events={events}
            decisions={decisions}
            artifacts={artifacts}
            onClose={onClose}
            onVeto={onVeto}
          />
        )}
      </motion.aside>
    </AnimatePresence>
  );
}

// -- Step Detail --
function StepDetail({
  projectId,
  step,
  events,
  decisions,
  artifacts,
  onClose,
  onVeto,
}: {
  projectId: string;
  step: string;
  events: WsEvent[];
  decisions: Decision[];
  artifacts: Artifact[];
  onClose: () => void;
  onVeto: (id: string) => void;
}) {
  const [summaries, setSummaries] = useState<DiscussionSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);

  const info = useMemo(() => computeStepInfo(events, step), [events, step]);
  const teamColor = info.team ? hashColor(info.team) : "#86868b";
  const stepDecisions = decisions.filter((d) => d.team === info.team);
  const stepArtifacts = artifacts.filter((a) => a.team === info.team);

  // Fetch round summaries
  useEffect(() => {
    if (info.team) {
      api.getSummaries(projectId, info.team).then(setSummaries).catch(() => {});
    }
  }, [projectId, info.team]);

  // Transcript events
  const transcriptEvents = useMemo(() => {
    return events.filter(
      (e) =>
        e.type === "agent_message" &&
        (e.data.step === step || e.data.team === info.team)
    );
  }, [events, step, info.team]);

  const filteredTranscript = useMemo(() => {
    if (!searchQuery) return transcriptEvents;
    const q = searchQuery.toLowerCase();
    return transcriptEvents.filter(
      (e) =>
        String(e.data.content ?? "").toLowerCase().includes(q) ||
        String(e.data.agent ?? "").toLowerCase().includes(q)
    );
  }, [transcriptEvents, searchQuery]);

  return (
    <>
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-[rgba(0,0,0,0.06)]">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full" style={{ backgroundColor: teamColor }} />
            <h3 className="text-[14px] font-semibold text-[#1d1d1f]">{step}</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded-md text-[#86868b] hover:text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.04)] transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {info.team && <Badge variant="neutral" size="sm">{info.team}</Badge>}
          {info.mode && <Badge variant="info" size="sm">{info.mode}</Badge>}
          {info.attempts > 1 && <Badge variant="warning" size="sm">{info.attempts}× attempts</Badge>}
          <span className="text-[10px] text-[#86868b]">{info.rounds} round{info.rounds !== 1 ? "s" : ""}</span>
        </div>
        {info.confidence !== undefined && (
          <div className="mt-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-medium text-[#86868b]">Confidence</span>
              <span className="text-[11px] font-semibold text-[#1d1d1f]">
                {Math.round(info.confidence * 100)}%
              </span>
            </div>
            <Progress value={info.confidence} />
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="rounds" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="shrink-0 px-2">
          <TabsTrigger value="rounds">
            <Layers className="h-3 w-3 mr-1 inline-block" /> Rounds
          </TabsTrigger>
          <TabsTrigger value="board">
            <MessageSquare className="h-3 w-3 mr-1 inline-block" /> Board
          </TabsTrigger>
          <TabsTrigger value="decisions">
            <MessageSquare className="h-3 w-3 mr-1 inline-block" /> Decisions
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <FileText className="h-3 w-3 mr-1 inline-block" /> Artifacts
          </TabsTrigger>
          <TabsTrigger value="transcript">
            <Scroll className="h-3 w-3 mr-1 inline-block" /> Transcript
          </TabsTrigger>
          <TabsTrigger value="gate">
            <ShieldCheck className="h-3 w-3 mr-1 inline-block" /> Gate
          </TabsTrigger>
        </TabsList>

        {/* Board tab */}
        <TabsContent value="board" className="flex-1 overflow-auto px-4 pb-4">
          <BoardPanel events={events} />
        </TabsContent>

        {/* Rounds tab */}
        <TabsContent value="rounds" className="flex-1 overflow-auto px-4 pb-4">
          {summaries.length === 0 ? (
            <EmptyTab text="No round summaries yet" />
          ) : (
            <div className="space-y-3">
              {summaries.map((s) => (
                <RoundSummaryCard key={s.id} summary={s} />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Decisions tab */}
        <TabsContent value="decisions" className="flex-1 overflow-auto px-4 pb-4">
          {stepDecisions.length === 0 ? (
            <EmptyTab text="No decisions for this step" />
          ) : (
            <div className="space-y-2">
              {stepDecisions.map((d) => (
                <DecisionRow
                  key={d.id}
                  decision={d}
                  expanded={expandedDecision === d.id}
                  onToggle={() => setExpandedDecision(expandedDecision === d.id ? null : d.id)}
                  onVeto={() => onVeto(d.id)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Artifacts tab */}
        <TabsContent value="artifacts" className="flex-1 overflow-auto px-4 pb-4">
          {stepArtifacts.length === 0 ? (
            <EmptyTab text="No artifacts for this step" />
          ) : (
            <div className="space-y-2">
              {stepArtifacts.map((a) => (
                <ArtifactRow key={a.id} artifact={a} />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Transcript tab */}
        <TabsContent value="transcript" className="flex-1 overflow-hidden flex flex-col">
          <div className="px-4 mb-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-[#86868b]" />
              <Input
                placeholder="Search transcript..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 h-7 text-[11px]"
              />
            </div>
          </div>
          <ScrollArea className="flex-1 px-4 pb-4">
            {filteredTranscript.length === 0 ? (
              <EmptyTab text="No transcript events" />
            ) : (
              <div className="space-y-2">
                {filteredTranscript.map((e, i) => (
                  <div key={i} className="flex gap-2 text-[12px]">
                    <Avatar name={(e.data.agent as string) ?? "Agent"} size="sm" className="mt-0.5 h-5 w-5 text-[8px]" />
                    <div className="min-w-0">
                      <span className="font-medium text-[#1d1d1f]">{e.data.agent as string}</span>
                      <p className="text-[#6e6e73] line-clamp-3">{String(e.data.content ?? "").slice(0, 200)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </TabsContent>

        {/* Gate tab */}
        <TabsContent value="gate" className="flex-1 overflow-auto px-4 pb-4">
          {info.gateResult ? (
            <div className="space-y-3">
              <div className={cn(
                "p-4 rounded-xl border",
                info.gateResult.toLowerCase().includes("return")
                  ? "bg-[#fef2f2] border-[#fecaca]/50"
                  : "bg-[#f0fdf4] border-[#bbf7d0]/50"
              )}>
                <div className="flex items-center gap-2 mb-2">
                  <ShieldCheck className={cn(
                    "h-5 w-5",
                    info.gateResult.toLowerCase().includes("return") ? "text-[#ff3b30]" : "text-[#34c759]"
                  )} />
                  <span className="text-[14px] font-semibold">
                    {info.gateResult.toLowerCase().includes("return") ? "Work Returned" : "Passed"}
                  </span>
                </div>
                <p className="text-[13px] text-[#1d1d1f]">{info.gateResult}</p>
                {info.gateNotes && <p className="mt-2 text-[12px] text-[#6e6e73]">{info.gateNotes}</p>}
              </div>
            </div>
          ) : (
            <EmptyTab text="No gate result yet" />
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}

// -- Project Summary (no step selected) --
function ProjectSummary({
  projectId,
  events,
  decisions,
  artifacts,
  onClose,
  onVeto,
}: {
  projectId: string;
  events: WsEvent[];
  decisions: Decision[];
  artifacts: Artifact[];
  onClose: () => void;
  onVeto: (id: string) => void;
}) {
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null);
  const [questions, setQuestions] = useState<api.OpenQuestion[]>([]);

  useEffect(() => {
    api.getQuestions(projectId).then(setQuestions).catch(() => {});
  }, [projectId]);

  // Aggregate stats
  const stats = useMemo(() => {
    const steps = new Set<string>();
    let totalRounds = 0;
    for (const e of events) {
      if (e.type === "workflow_step_start") steps.add(e.data.step as string);
      if (e.type === "team_round_end") totalRounds++;
    }
    return { steps: steps.size, rounds: totalRounds };
  }, [events]);

  return (
    <>
      <div className="shrink-0 px-4 py-3 border-b border-[rgba(0,0,0,0.06)] flex items-center justify-between">
        <h3 className="text-[14px] font-semibold text-[#1d1d1f]">Project Overview</h3>
        <button onClick={onClose} className="p-1 rounded-md text-[#86868b] hover:text-[#1d1d1f] hover:bg-[rgba(0,0,0,0.04)] transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <ScrollArea className="flex-1">
        <div className="px-4 py-4 space-y-6">
          {/* Stats */}
          <div className="grid grid-cols-3 gap-2">
            <MiniStat label="Steps" value={String(stats.steps)} />
            <MiniStat label="Rounds" value={String(stats.rounds)} />
            <MiniStat label="Decisions" value={String(decisions.length)} />
          </div>

          {/* Decisions */}
          <section>
            <h4 className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5" /> Decisions ({decisions.length})
            </h4>
            <div className="space-y-2">
              {decisions.slice(0, 10).map((d) => (
                <DecisionRow
                  key={d.id}
                  decision={d}
                  expanded={expandedDecision === d.id}
                  onToggle={() => setExpandedDecision(expandedDecision === d.id ? null : d.id)}
                  onVeto={() => onVeto(d.id)}
                />
              ))}
              {decisions.length === 0 && <EmptyTab text="No decisions yet" />}
            </div>
          </section>

          {/* Artifacts */}
          <section>
            <h4 className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <FileText className="h-3.5 w-3.5" /> Artifacts ({artifacts.length})
            </h4>
            <div className="space-y-2">
              {artifacts.slice(0, 8).map((a) => (
                <ArtifactRow key={a.id} artifact={a} />
              ))}
              {artifacts.length === 0 && <EmptyTab text="No artifacts yet" />}
            </div>
          </section>

          {/* Open Questions */}
          {questions.length > 0 && (
            <section>
              <h4 className="text-[12px] font-semibold text-[#86868b] uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <HelpCircle className="h-3.5 w-3.5" /> Open Questions ({questions.length})
              </h4>
              <div className="space-y-2">
                {questions.map((q) => (
                  <div key={q.id} className="px-3 py-2 rounded-lg bg-[#f5f5f7] text-[12px]">
                    <p className="font-medium text-[#1d1d1f]">{q.question}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="neutral" size="sm">{q.raised_by}</Badge>
                      <Badge variant={q.status === "open" ? "warning" : "success"} size="sm">{q.status}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </ScrollArea>
    </>
  );
}

// -- Shared sub-components --
function DecisionRow({
  decision,
  expanded,
  onToggle,
  onVeto,
}: {
  decision: Decision;
  expanded: boolean;
  onToggle: () => void;
  onVeto: () => void;
}) {
  const conf = decision.confidence;
  return (
    <div className="rounded-lg border border-[rgba(0,0,0,0.06)] overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[rgba(0,0,0,0.02)] transition-colors"
      >
        {expanded ? <ChevronDown className="h-3 w-3 text-[#86868b] shrink-0" /> : <ChevronRight className="h-3 w-3 text-[#86868b] shrink-0" />}
        <span className="text-[12px] font-medium text-[#1d1d1f] flex-1 truncate">{decision.topic}</span>
        <ConfidenceRing value={conf} size={18} strokeWidth={2} />
      </button>
      {expanded && (
        <div className="px-3 pb-3 border-t border-[rgba(0,0,0,0.04)]">
          <p className="text-[12px] text-[#1d1d1f] mt-2 mb-1">{decision.decision}</p>
          {decision.rationale && (
            <p className="text-[11px] text-[#86868b] italic">"{decision.rationale}"</p>
          )}
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-1.5">
              <Badge variant="neutral" size="sm">{decision.team}</Badge>
              <StatusBadge status={decision.status} className="text-[9px]" />
            </div>
            {decision.status === "active" && (
              <Button variant="destructive" size="sm" onClick={onVeto} className="h-6 text-[10px] px-2">
                Veto
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ArtifactRow({ artifact }: { artifact: Artifact }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border border-[rgba(0,0,0,0.06)] overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[rgba(0,0,0,0.02)] transition-colors"
      >
        <FileText className="h-3.5 w-3.5 text-[#af52de] shrink-0" />
        <span className="text-[12px] font-medium text-[#1d1d1f] flex-1 truncate">{artifact.name}</span>
        <Badge variant="neutral" size="sm">{artifact.type}</Badge>
      </button>
      {expanded && artifact.content && (
        <div className="px-3 pb-3 border-t border-[rgba(0,0,0,0.04)]">
          <pre className="text-[11px] text-[#6e6e73] mt-2 whitespace-pre-wrap font-mono max-h-48 overflow-auto bg-[#f5f5f7] rounded-md p-2">
            {artifact.content.slice(0, 2000)}
          </pre>
        </div>
      )}
    </div>
  );
}

function RoundSummaryCard({ summary }: { summary: DiscussionSummary }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card className="p-0 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-[rgba(0,0,0,0.02)] transition-colors"
      >
        {expanded ? <ChevronDown className="h-3 w-3 text-[#86868b]" /> : <ChevronRight className="h-3 w-3 text-[#86868b]" />}
        <span className="text-[12px] font-semibold text-[#1d1d1f]">Round {summary.round_number}</span>
        <span className="text-[11px] text-[#86868b] truncate flex-1">{summary.topic}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-3 border-t border-[rgba(0,0,0,0.04)] space-y-2">
          {summary.key_points.length > 0 && (
            <div>
              <span className="text-[10px] font-semibold text-[#86868b] uppercase">Key Points</span>
              <ul className="mt-1 space-y-0.5">
                {summary.key_points.map((p, i) => (
                  <li key={i} className="text-[11px] text-[#6e6e73] flex gap-1.5">
                    <span className="text-[#0071e3] shrink-0">•</span>
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {summary.conclusions.length > 0 && (
            <div>
              <span className="text-[10px] font-semibold text-[#86868b] uppercase">Conclusions</span>
              <ul className="mt-1 space-y-0.5">
                {summary.conclusions.map((c, i) => (
                  <li key={i} className="text-[11px] text-[#1d1d1f] font-medium flex gap-1.5">
                    <span className="text-[#34c759] shrink-0">✓</span>
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {summary.unresolved_items.length > 0 && (
            <div>
              <span className="text-[10px] font-semibold text-[#86868b] uppercase">Unresolved</span>
              <ul className="mt-1 space-y-0.5">
                {summary.unresolved_items.map((u, i) => (
                  <li key={i} className="text-[11px] text-[#ff9500] flex gap-1.5">
                    <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                    {u}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-2 rounded-lg bg-[#f5f5f7] text-center">
      <p className="text-[16px] font-semibold text-[#1d1d1f] tabular-nums">{value}</p>
      <p className="text-[10px] text-[#86868b] font-medium">{label}</p>
    </div>
  );
}

function EmptyTab({ text }: { text: string }) {
  return <p className="text-[12px] text-[#86868b] py-8 text-center">{text}</p>;
}

// -- Step info computation --
function computeStepInfo(events: WsEvent[], step: string): StepInfo {
  let team: string | undefined;
  let mode: string | undefined;
  let rounds = 0;
  let confidence: number | undefined;
  let gateResult: string | undefined;
  let gateNotes: string | undefined;
  let attempts = 1;
  let startTime: number | undefined;
  let endTime: number | undefined;

  for (const e of events) {
    if (e.data.step !== step) continue;

    if (e.type === "workflow_step_start") {
      team = e.data.team as string;
      attempts = (e.data.attempt as number) ?? 1;
      startTime = new Date(e.timestamp).getTime();
    }
    if (e.type === "workflow_step_complete") {
      endTime = new Date(e.timestamp).getTime();
    }
    if (e.type === "team_mode_selected") mode = e.data.mode as string;
    if (e.type === "team_round_end") {
      rounds++;
      if (typeof e.data.confidence === "number") confidence = e.data.confidence as number;
    }
    if (e.type === "forum_gate_result") {
      gateResult = e.data.result as string;
      gateNotes = e.data.notes as string;
    }
  }

  const duration = startTime && endTime ? endTime - startTime : undefined;
  return { team, mode, rounds, duration, confidence, gateResult, gateNotes, attempts };
}
