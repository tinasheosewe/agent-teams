import { create } from "zustand";

export interface WsEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
  project_id: string;
}

export interface Toast {
  id: string;
  kind: "error" | "warning" | "info" | "success";
  title: string;
  detail?: string;
  step?: string;
  createdAt: number;
}

interface EventState {
  eventsByProject: Map<string, WsEvent[]>;
  toasts: Toast[];
  connections: Map<string, WebSocket>;

  connectProject: (projectId: string) => void;
  disconnectProject: (projectId: string) => void;
  disconnectAll: () => void;
  sendMessage: (projectId: string, action: string, message: string) => void;
  addToast: (toast: Omit<Toast, "id" | "createdAt">) => void;
  dismissToast: (id: string) => void;
  clearEvents: (projectId: string) => void;
  getEvents: (projectId: string) => WsEvent[];
  isConnected: (projectId: string) => boolean;
}

let toastCounter = 0;

function extractToast(event: WsEvent): Omit<Toast, "id" | "createdAt"> | null {
  const { type, data } = event;
  if (type === "decision_made") {
    const conf = data.confidence as number;
    if (conf < 0.4) return { kind: "error", title: "Low-confidence decision", detail: data.topic as string, step: data.step as string };
    if (conf < 0.6) return { kind: "warning", title: "Uncertain decision", detail: data.topic as string, step: data.step as string };
  }
  if (type === "forum_gate_result" && typeof data.result === "string" && data.result.toLowerCase().includes("return")) {
    return { kind: "error", title: "Gate returned work", detail: data.notes as string, step: data.step as string };
  }
  if (type === "forum_escalation") {
    return { kind: "warning", title: "Escalation", detail: data.message as string };
  }
  if (type === "user_input_requested") {
    return { kind: "info", title: "Input needed", detail: data.question as string };
  }
  return null;
}

export const useEventStore = create<EventState>((set, get) => ({
  eventsByProject: new Map(),
  toasts: [],
  connections: new Map(),

  connectProject: (projectId: string) => {
    const existing = get().connections.get(projectId);
    if (existing && existing.readyState <= 1) return; // already open or connecting

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/projects/${projectId}`);

    ws.onmessage = (msg) => {
      try {
        const event: WsEvent = JSON.parse(msg.data);
        set((s) => {
          const next = new Map(s.eventsByProject);
          const list = [...(next.get(projectId) ?? []), event];
          next.set(projectId, list);

          const toast = extractToast(event);
          const toasts = toast
            ? [...s.toasts, { ...toast, id: String(++toastCounter), createdAt: Date.now() }].slice(-10)
            : s.toasts;

          return { eventsByProject: next, toasts };
        });
      } catch {
        // non-JSON message, ignore
      }
    };

    ws.onclose = () => {
      set((s) => {
        const next = new Map(s.connections);
        next.delete(projectId);
        return { connections: next };
      });
    };

    set((s) => {
      const next = new Map(s.connections);
      next.set(projectId, ws);
      return { connections: next };
    });
  },

  disconnectProject: (projectId: string) => {
    const ws = get().connections.get(projectId);
    if (ws) ws.close();
    set((s) => {
      const next = new Map(s.connections);
      next.delete(projectId);
      return { connections: next };
    });
  },

  disconnectAll: () => {
    for (const ws of get().connections.values()) ws.close();
    set({ connections: new Map() });
  },

  sendMessage: (projectId: string, action: string, message: string) => {
    const ws = get().connections.get(projectId);
    if (ws?.readyState === 1) {
      ws.send(JSON.stringify({ action, message }));
    }
  },

  addToast: (toast) => {
    set((s) => ({
      toasts: [...s.toasts, { ...toast, id: String(++toastCounter), createdAt: Date.now() }].slice(-10),
    }));
  },

  dismissToast: (id: string) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },

  clearEvents: (projectId: string) => {
    set((s) => {
      const next = new Map(s.eventsByProject);
      next.delete(projectId);
      return { eventsByProject: next };
    });
  },

  getEvents: (projectId: string) => {
    return get().eventsByProject.get(projectId) ?? [];
  },

  isConnected: (projectId: string) => {
    const ws = get().connections.get(projectId);
    return ws?.readyState === 1;
  },
}));
