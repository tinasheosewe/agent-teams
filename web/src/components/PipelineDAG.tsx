import { useMemo } from 'react'
import type { WsEvent } from '../hooks/useWebSocket'

/* ─── Types ─── */
interface StepNode {
  name: string
  team: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  attempt: number
  fastTracked: boolean
  confidence: number | null // aggregate of decisions in this step
}

interface LayoutNode extends StepNode {
  layer: number  // x-axis position (0-based)
  slot: number   // y-axis position within layer (0 for single, 0/1 for parallel)
  slotsInLayer: number
}

interface Props {
  events: WsEvent[]
  selectedNode: string | null
  onSelectNode: (name: string | null) => void
}

/* ─── Layout constants ─── */
const NODE_R = 22
const LAYER_GAP = 140
const SLOT_GAP = 72
const PAD_X = 60
const PAD_Y = 50
const LABEL_OFFSET = 16

/* ─── Colors ─── */
const STATUS_COLORS: Record<string, { fill: string; stroke: string }> = {
  pending:     { fill: 'transparent',  stroke: 'var(--text-4)' },
  in_progress: { fill: 'var(--accent-dim)', stroke: 'var(--accent)' },
  completed:   { fill: 'var(--green-dim)', stroke: 'var(--green)' },
  failed:      { fill: 'var(--red-dim)', stroke: 'var(--red)' },
}

function confColor(c: number): string {
  if (c >= 0.8) return 'var(--green)'
  if (c >= 0.5) return 'var(--yellow)'
  return 'var(--red)'
}

/* ─── Build step list from events ─── */
function buildSteps(events: WsEvent[]): StepNode[] {
  const map = new Map<string, StepNode>()
  const ordered: string[] = []
  const decisionConfs = new Map<string, number[]>()

  // Track which step is "current" for attributing decisions
  let currentStep: string | null = null

  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && evt.data.step) {
      const name = String(evt.data.step)
      currentStep = name
      if (!map.has(name)) {
        map.set(name, {
          name,
          team: String(evt.data.team || name),
          status: 'in_progress',
          attempt: Number(evt.data.attempt ?? 1),
          fastTracked: false,
          confidence: null,
        })
        ordered.push(name)
      } else {
        const node = map.get(name)!
        node.status = 'in_progress'
        node.attempt = Number(evt.data.attempt ?? node.attempt)
      }
    }
    if (evt.type === 'workflow_step_complete' && evt.data.step) {
      const name = String(evt.data.step)
      const node = map.get(name)
      if (node) {
        node.status = 'completed'
        if (evt.data.fast_tracked) node.fastTracked = true
      }
      if (currentStep === name) currentStep = null
    }
    if (evt.type === 'decision_made' && currentStep) {
      const conf = Number(evt.data.confidence ?? 0)
      if (!decisionConfs.has(currentStep)) decisionConfs.set(currentStep, [])
      decisionConfs.get(currentStep)!.push(conf)
    }
  }

  // Compute aggregate confidence per step
  for (const [step, confs] of decisionConfs) {
    const node = map.get(step)
    if (node && confs.length > 0) {
      node.confidence = confs.reduce((a, b) => a + b, 0) / confs.length
    }
  }

  return ordered.map(name => map.get(name)!)
}

/* ─── Component ─── */
export default function PipelineDAG({ events, selectedNode, onSelectNode }: Props) {
  const steps = useMemo(() => buildSteps(events), [events])
  const nodes = useMemo(() => {
    if (steps.length === 0) return []

    // Better parallel detection: scan events for overlapping step_start without intervening step_complete
    const startOrder: string[] = []
    const completedBefore = new Set<string>()
    const parallelPairs = new Set<string>()

    for (const evt of events) {
      if (evt.type === 'workflow_step_start' && evt.data.step) {
        const name = String(evt.data.step)
        // Check if previous started step hasn't completed yet
        for (const prev of startOrder) {
          if (!completedBefore.has(prev)) {
            // prev and name are running in parallel
            parallelPairs.add([prev, name].sort().join('|'))
          }
        }
        startOrder.push(name)
      }
      if (evt.type === 'workflow_step_complete' && evt.data.step) {
        completedBefore.add(String(evt.data.step))
      }
    }

    // Assign layers with parallel awareness
    const result: LayoutNode[] = []
    let layer = 0
    const placed = new Set<string>()

    for (let i = 0; i < steps.length; i++) {
      if (placed.has(steps[i].name)) continue
      // Find all steps parallel with this one
      const group = [steps[i]]
      for (let j = i + 1; j < steps.length; j++) {
        if (placed.has(steps[j].name)) continue
        const key = [steps[i].name, steps[j].name].sort().join('|')
        if (parallelPairs.has(key)) {
          group.push(steps[j])
        }
      }
      for (let s = 0; s < group.length; s++) {
        result.push({ ...group[s], layer, slot: s, slotsInLayer: group.length })
        placed.add(group[s].name)
      }
      layer++
    }

    return result
  }, [steps, events])

  const layerCount = nodes.length > 0 ? Math.max(...nodes.map(n => n.layer)) + 1 : 0
  const maxSlots = nodes.length > 0 ? Math.max(...nodes.map(n => n.slotsInLayer)) : 1
  const svgW = PAD_X * 2 + (layerCount - 1) * LAYER_GAP + NODE_R * 2
  const svgH = PAD_Y * 2 + (maxSlots - 1) * SLOT_GAP + NODE_R * 2 + LABEL_OFFSET + 14

  function nodeX(n: LayoutNode) { return PAD_X + n.layer * LAYER_GAP + NODE_R }
  function nodeY(n: LayoutNode) {
    const centerY = svgH / 2 - LABEL_OFFSET / 2
    if (n.slotsInLayer === 1) return centerY
    const groupHeight = (n.slotsInLayer - 1) * SLOT_GAP
    return centerY - groupHeight / 2 + n.slot * SLOT_GAP
  }

  // Build edges: connect each node to nodes in the next layer
  const edges: { x1: number; y1: number; x2: number; y2: number; active: boolean }[] = []
  for (const node of nodes) {
    const nextLayer = nodes.filter(n => n.layer === node.layer + 1)
    for (const next of nextLayer) {
      edges.push({
        x1: nodeX(node) + NODE_R,
        y1: nodeY(node),
        x2: nodeX(next) - NODE_R,
        y2: nodeY(next),
        active: node.status === 'completed' || node.status === 'in_progress',
      })
    }
  }

  if (nodes.length === 0) {
    return (
      <div className="dag-strip">
        <div className="dag-empty">Waiting for workflow to start...</div>
      </div>
    )
  }

  return (
    <div className="dag-strip">
      <svg
        className="dag-svg"
        viewBox={`0 0 ${svgW} ${svgH}`}
        width={svgW}
        height={svgH}
      >
        {/* Edges */}
        {edges.map((e, i) => {
          const mx = (e.x1 + e.x2) / 2
          return (
            <path
              key={`e-${i}`}
              d={`M ${e.x1} ${e.y1} C ${mx} ${e.y1}, ${mx} ${e.y2}, ${e.x2} ${e.y2}`}
              className={`dag-edge ${e.active ? 'dag-edge-active' : ''}`}
            />
          )
        })}

        {/* Nodes */}
        {nodes.map(node => {
          const cx = nodeX(node)
          const cy = nodeY(node)
          const colors = STATUS_COLORS[node.status] || STATUS_COLORS.pending
          const isSelected = selectedNode === node.name

          return (
            <g
              key={node.name}
              className={`dag-node ${node.status} ${isSelected ? 'selected' : ''} ${node.fastTracked ? 'fast-tracked' : ''}`}
              onClick={() => onSelectNode(isSelected ? null : node.name)}
              style={{ cursor: 'pointer' }}
            >
              {/* Confidence ring */}
              {node.confidence !== null && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={NODE_R + 4}
                  fill="none"
                  stroke={confColor(node.confidence)}
                  strokeWidth={2.5}
                  strokeDasharray={`${node.confidence * 2 * Math.PI * (NODE_R + 4)} ${(1 - node.confidence) * 2 * Math.PI * (NODE_R + 4)}`}
                  strokeDashoffset={0.25 * 2 * Math.PI * (NODE_R + 4)}
                  strokeLinecap="round"
                  opacity={0.7}
                />
              )}

              {/* Selection ring */}
              {isSelected && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={NODE_R + 7}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth={1.5}
                  opacity={0.4}
                />
              )}

              {/* Main circle */}
              <circle
                cx={cx}
                cy={cy}
                r={NODE_R}
                fill={colors.fill}
                stroke={colors.stroke}
                strokeWidth={2}
                className={node.status === 'in_progress' ? 'dag-pulse' : ''}
              />

              {/* Glow for active */}
              {node.status === 'in_progress' && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={NODE_R}
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth={6}
                  opacity={0.15}
                  className="dag-glow"
                />
              )}

              {/* Status icon */}
              <text
                x={cx}
                y={cy}
                textAnchor="middle"
                dominantBaseline="central"
                className="dag-icon"
                fill={colors.stroke}
              >
                {node.status === 'completed' ? '✓' : node.status === 'failed' ? '✕' : node.fastTracked ? '⚡' : ''}
              </text>

              {/* Label */}
              <text
                x={cx}
                y={cy + NODE_R + LABEL_OFFSET}
                textAnchor="middle"
                className="dag-label"
              >
                {node.name}
              </text>

              {/* Attempt badge */}
              {node.attempt > 1 && (
                <g>
                  <circle cx={cx + NODE_R - 2} cy={cy - NODE_R + 2} r={7} fill="var(--yellow)" />
                  <text
                    x={cx + NODE_R - 2}
                    y={cy - NODE_R + 2}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className="dag-attempt"
                  >
                    {node.attempt}
                  </text>
                </g>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
