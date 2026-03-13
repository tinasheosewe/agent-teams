import { create } from "zustand";
import * as api from "../api";
import type { ConfigInfo } from "../api";

interface ConfigState {
  configs: ConfigInfo[];
  selectedConfigName: string | null;
  configDetails: Map<string, Record<string, unknown>>;

  fetchConfigs: () => Promise<void>;
  selectConfig: (name: string | null) => void;
  fetchConfigDetail: (name: string) => Promise<Record<string, unknown>>;
  selectedConfig: () => ConfigInfo | undefined;
}

export const useConfigStore = create<ConfigState>((set, get) => ({
  configs: [],
  selectedConfigName: null,
  configDetails: new Map(),

  fetchConfigs: async () => {
    const configs = await api.listConfigs();
    set({ configs });
    if (!get().selectedConfigName && configs.length > 0) {
      set({ selectedConfigName: configs[0].name });
    }
  },

  selectConfig: (name: string | null) => set({ selectedConfigName: name }),

  fetchConfigDetail: async (name: string) => {
    const existing = get().configDetails.get(name);
    if (existing) return existing;
    const detail = await api.getConfigDetail(name);
    set((s) => {
      const next = new Map(s.configDetails);
      next.set(name, detail);
      return { configDetails: next };
    });
    return detail;
  },

  selectedConfig: () => {
    const { configs, selectedConfigName } = get();
    return configs.find((c) => c.name === selectedConfigName);
  },
}));
