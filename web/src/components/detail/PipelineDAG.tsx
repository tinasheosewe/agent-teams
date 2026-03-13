import { useMemo, useCallback } from "react";
import { hashColor } from "../../lib/utils";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../ui/Tooltip";
import { ConfidenceRing } from "../ui/Progress";
import type { WsEvent } from "../../stores/eventStore";

interface StepNode {
  name: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  team?: string;
  confidence?: number;
  attempts: number;
  layer: number;
  slot: number;
  mode?: string;
  fastTracked?: boolean;
}

interface Props {
  events: WsEvent[];
  selectedStep: string | null;
  onSelectStep: (step: string | null) => void;
}

// Layout constants
const NODE_W = 140;
const NODE_H = 44;
const LAYER_GAP = 180;
const SLOT_GAP = 72;
const PAD_X = 60;
const PAD_Y = 50;

export function PipelineDAG({ events, selectedStep, onSelectStep }: Props) {
  const { nodes, edges } = useMemo(() => buildGraph(events), [events]);

  const maxLayer = Math.max(0, ...nodes.map((n) => n.layer));
  const maxSlot = Math.max(0, ...nodes.map((n) => n.slot));
  const svgW = (maxLayer + 1) * LAYER_GAP + PAD_X * 2;
  const svgH = (maxSlot + 1) * SLOT_GAP + PAD_Y * 2;

  const nodePos = useCallback(
    (n: StepNode) => ({
      x: PAD_X + n.layer * LAYER_GAP + NODE_W / 2,
      y: PAD_Y + n.slot * SLOT_GAP + NODE_H / 2,
    }),
    []
  );

  if (nodes.length === 0) return null;

  return (
    <TooltipProvider delayDuration={200}>
      <div className="w-full overflow-x-auto bg-gradient-to-b from-white to-[#fafafa] border-b border-[rgba(0,0,0,0.06)]">
        <svg
          width={svgW}
          height={svgH}
          className="min-w-full"
          style={{ minHeight: Math.max(130, svgH) }}
        >
          {/* Edges */}
          {edges.map(([from, to], i) => {
            const a = nodes.find((n) => n.name === from);
            const b = nodes.find((n) => n.name === to);
            if (!a || !b) return null;
            const p1 = nodePos(a);
            const p2 = nodePos(b);
            const mx = (p1.x + p2.x) / 2;
            return (
              <path
                key={i}
                d={`M ${p1.x + NODE_W / 2} ${p1.y} C ${mx} ${p1.y}, ${mx} ${p2.y}, ${p2.x - NODE_W / 2} ${p2.y}`}
                fill="none"
                stroke="rgba(0,0,0,0.1)"
                strokeWidth={1.5}
                strokeLinecap="round"
              />
            );
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const pos = nodePos(node);
            const isSelected = selectedStep === node.name;
            const teamColor = node.team ? hashColor(node.team) : "#86868b";
            return (
              <Tooltip key={node.name}>
                <TooltipTrigger asChild>
                  <g
                    className="cursor-pointer"
                    onClick={() => onSelectStep(isSelected ? null : node.name)}
                  >
                    {/* Selection glow */}
                    {isSelected && (
                      <rect
                        x={pos.x - NODE_W / 2 - 4}
                        y={pos.y - NODE_H / 2 - 4}
                        width={NODE_W + 8}
                        height={NODE_H + 8}
                        rx={16}
                        ry={16}
                        fill="none"
                        stroke="#0071e3"
                        strokeWidth={2}
                        opacity={0.4}
                      />
                    )}

                    {/* In-progress pulse */}
                    {node.status === "in_progress" && (
                      <rect
                        x={pos.x - NODE_W / 2 - 2}
                        y={pos.y - NODE_H / 2 - 2}
                        width={NODE_W + 4}
                        height={NODE_H + 4}
                        rx={14}
                        ry={14}
                        fill="none"
                        stroke="#0071e3"
                        strokeWidth={1.5}
                        opacity={0.3}
                        className="animate-pulse"
                      />
                    )}

                    {/* Node body */}
                    <rect
                      x={pos.x - NODE_W / 2}
                      y={pos.y - NODE_H / 2}
                      width={NODE_W}
                      height={NODE_H}
                      rx={12}
                      ry={12}
                      fill={
                        node.status === "completed"
                          ? "#f0fdf4"
                          : node.status === "failed"
                          ? "#fef2f2"
                          : node.status === "in_progress"
                          ? "#eff6ff"
                          : "#ffffff"
                      }
                      stroke={
                        node.status === "completed"
                          ? "#bbf7d0"
                          : node.status === "failed"
                          ? "#fecaca"
                          : node.status === "in_progress"
                          ? "#bfdbfe"
                          : "rgba(0,0,0,0.08)"
                      }
                      strokeWidth={1.5}
                      className="transition-all duration-200"
                    />

                    {/* Team color accent line */}
                    <rect
                      x={pos.x - NODE_W / 2}
                      y={pos.y - NODE_H / 2}
                      width={4}
                      height={NODE_H}
                      rx={2}
                      fill={teamColor}
                    />

                    {/* Step name */}
                    <text
                      x={pos.x + 4}
                      y={pos.y - 3}
                      textAnchor="middle"
                      className="text-[11px] font-semibold fill-[#1d1d1f]"
                    >
                      {truncateStep(node.name)}
                    </text>

                    {/* Team name sub-label */}
                    {node.team && (
                      <text
                        x={pos.x + 4}
                        y={pos.y + 11}
                        textAnchor="middle"
                        className="text-[9px] fill-[#86868b]"
                      >
                        {node.team}
                      </text>
                    )}

                    {/* Status icon */}
                    {node.status === "completed" && (
                      <g transform={`translate(${pos.x + NODE_W / 2 - 12}, ${pos.y - NODE_H / 2 - 6})`}>
                        <circle cx={8} cy={8} r={8} fill="#34c759" />
                        <path d="M5 8 L7 10 L11 6" stroke="white" strokeWidth={1.5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
                      </g>
                    )}

                    {node.status === "failed" && (
                      <g transform={`translate(${pos.x + NODE_W / 2 - 12}, ${pos.y - NODE_H / 2 - 6})`}>
                        <circle cx={8} cy={8} r={8} fill="#ff3b30" />
                        <path d="M5.5 5.5 L10.5 10.5 M10.5 5.5 L5.5 10.5" stroke="white" strokeWidth={1.5} strokeLinecap="round" />
                      </g>
                    )}

                    {/* Attempt badge */}
                    {node.attempts > 1 && (
                      <g transform={`translate(${pos.x - NODE_W / 2 + 4}, ${pos.y - NODE_H / 2 - 6})`}>
                        <rect width={20} height={14} rx={7} fill="#ff9500" />
                        <text x={10} y={10.5} textAnchor="middle" className="text-[9px] font-bold fill-white">
                          {node.attempts}×
                        </text>
                      </g>
                    )}

                    {/* Confidence ring */}
                    {node.confidence !== undefined && node.status !== "pending" && (
                      <foreignObject
                        x={pos.x + NODE_W / 2 - 24}
                        y={pos.y + NODE_H / 2 - 10}
                        width={24}
                        height={24}
                      >
                        <ConfidenceRing value={node.confidence} size={24} strokeWidth={2.5} />
                      </foreignObject>
                    )}
                  </g>
                </TooltipTrigger>
                <TooltipContent>
                  <div className="space-y-1">
                    <p className="font-semibold">{node.name}</p>
                    {node.team && <p className="text-[#6e6e73]">Team: {node.team}</p>}
                    {node.mode && <p className="text-[#6e6e73]">Mode: {node.mode}</p>}
                    {node.confidence !== undefined && (
                      <p className="text-[#6e6e73]">Confidence: {Math.round(node.confidence * 100)}%</p>
                    )}
                    {node.attempts > 1 && <p className="text-[#ff9500]">Attempts: {node.attempts}</p>}
                  </div>
                </TooltipContent>
              </Tooltip>
            );
          })}
        </svg>
      </div>
    </TooltipProvider>
  );
}

// -- Graph builder --
function buildGraph(events: WsEvent[]): { nodes: StepNode[]; edges: [string, string][] } {
  const stepMap = new Map<string, StepNode>();
  const edges: [string, string][] = [];
  let prevStep: string | null = null;
  const activeSteps = new Set<string>();
  const parallelGroups = new Map<string, number>(); // step -> slot

  for (const e of events) {
    const stepName = e.data.step as string | undefined;
    if (!stepName) continue;

    if (e.type === "workflow_step_start") {
      let existing = stepMap.get(stepName);
      if (!existing) {
        // Determine if parallel
        let slot = 0;
        if (activeSteps.size > 0) {
          slot = activeSteps.size;
        }
        existing = {
          name: stepName,
          status: "in_progress",
          team: e.data.team as string | undefined,
          attempts: e.data.attempt as number ?? 1,
          layer: stepMap.size,
          slot,
          mode: undefined,
          confidence: undefined,
        };
        stepMap.set(stepName, existing);
        parallelGroups.set(stepName, slot);
      } else {
        existing.status = "in_progress";
        existing.attempts = (e.data.attempt as number) ?? existing.attempts;
      }
      activeSteps.add(stepName);

      if (prevStep && prevStep !== stepName && !activeSteps.has(prevStep)) {
        edges.push([prevStep, stepName]);
      }
    }

    if (e.type === "workflow_step_complete") {
      const node = stepMap.get(stepName);
      if (node) {
        node.status = "completed";
        if (e.data.fast_tracked) node.fastTracked = true;
      }
      activeSteps.delete(stepName);
      prevStep = stepName;
    }

    if (e.type === "team_mode_selected") {
      const node = stepMap.get(stepName);
      if (node) node.mode = e.data.mode as string;
    }

    if (e.type === "decision_made" || e.type === "team_round_end") {
      const node = stepMap.get(stepName);
      if (node && typeof e.data.confidence === "number") {
        node.confidence = e.data.confidence as number;
      }
    }

    // Detect team from round events
    if ((e.type === "team_round_start" || e.type === "team_round_end") && e.data.team) {
      const node = stepMap.get(stepName);
      if (node) node.team = e.data.team as string;
    }
  }

  // Resolve parallel layout: set layer correctly for parallel steps
  const nodes = Array.from(stepMap.values());
  // Re-number layers based on parallel detection
  let currentLayer = 0;
  const layerAssigned = new Set<string>();
  for (const n of nodes) {
    if (layerAssigned.has(n.name)) continue;
    n.layer = currentLayer;
    layerAssigned.add(n.name);
    // Find parallel steps (same slot group proximity)
    for (const other of nodes) {
      if (!layerAssigned.has(other.name) && Math.abs(other.slot - n.slot) > 0 && other.layer === n.layer) {
        other.layer = currentLayer;
        layerAssigned.add(other.name);
      }
    }
    currentLayer++;
  }

  return { nodes, edges };
}

function truncateStep(name: string): string {
  if (name.length <= 16) return name;
  return name.slice(0, 14) + "…";
}
