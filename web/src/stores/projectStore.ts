import { create } from "zustand";
import type { Project, Decision, Artifact } from "../api";
import * as api from "../api";

interface ProjectState {
  projects: Map<string, Project>;
  activeProjectId: string | null;
  decisions: Map<string, Decision[]>;
  artifacts: Map<string, Artifact[]>;

  // Derived
  activeProject: () => Project | undefined;
  projectList: () => Project[];
  runningProjects: () => Project[];
  projectsByConfig: (config: string) => Project[];

  // Actions
  fetchProjects: () => Promise<void>;
  fetchProject: (id: string) => Promise<void>;
  createProject: (prompt: string, configPath: string) => Promise<Project>;
  setActiveProject: (id: string | null) => void;
  fetchDecisions: (projectId: string) => Promise<void>;
  fetchArtifacts: (projectId: string) => Promise<void>;
  runProject: (id: string) => Promise<void>;
  pauseProject: (id: string) => Promise<void>;
  resumeProject: (id: string) => Promise<void>;
  killProject: (id: string) => Promise<void>;
  updateProject: (project: Project) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: new Map(),
  activeProjectId: null,
  decisions: new Map(),
  artifacts: new Map(),

  activeProject: () => {
    const { projects, activeProjectId } = get();
    return activeProjectId ? projects.get(activeProjectId) : undefined;
  },

  projectList: () => {
    return Array.from(get().projects.values()).sort(
      (a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()
    );
  },

  runningProjects: () => {
    return Array.from(get().projects.values()).filter((p) => p.status === "running");
  },

  projectsByConfig: (config: string) => {
    return Array.from(get().projects.values()).filter((p) => p.config_name === config);
  },

  fetchProjects: async () => {
    const list = await api.listProjects();
    const map = new Map<string, Project>();
    for (const p of list) map.set(p.id, p);
    set({ projects: map });
  },

  fetchProject: async (id: string) => {
    const p = await api.getProject(id);
    set((s) => {
      const next = new Map(s.projects);
      next.set(id, p);
      return { projects: next };
    });
  },

  createProject: async (prompt: string, configPath: string) => {
    const p = await api.createProject(prompt, configPath);
    set((s) => {
      const next = new Map(s.projects);
      next.set(p.id, p);
      return { projects: next, activeProjectId: p.id };
    });
    return p;
  },

  setActiveProject: (id: string | null) => set({ activeProjectId: id }),

  fetchDecisions: async (projectId: string) => {
    const d = await api.getDecisions(projectId);
    set((s) => {
      const next = new Map(s.decisions);
      next.set(projectId, d);
      return { decisions: next };
    });
  },

  fetchArtifacts: async (projectId: string) => {
    const a = await api.getArtifacts(projectId);
    set((s) => {
      const next = new Map(s.artifacts);
      next.set(projectId, a);
      return { artifacts: next };
    });
  },

  runProject: async (id: string) => {
    const p = await api.runProject(id);
    set((s) => {
      const next = new Map(s.projects);
      next.set(id, p);
      return { projects: next };
    });
  },

  pauseProject: async (id: string) => {
    await api.pauseProject(id);
    await get().fetchProject(id);
  },

  resumeProject: async (id: string) => {
    await api.resumeProject(id);
    await get().fetchProject(id);
  },

  killProject: async (id: string) => {
    await api.killProject(id);
    await get().fetchProject(id);
  },

  updateProject: (project: Project) => {
    set((s) => {
      const next = new Map(s.projects);
      next.set(project.id, project);
      return { projects: next };
    });
  },
}));
