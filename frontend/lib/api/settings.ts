import { DEFAULT_SETTINGS, readArchmindSettings, writeArchmindSettings } from "@/components/settingsStore";
import type { ArchmindSettings } from "@/types/settings";

export function loadSettings(): ArchmindSettings {
  try {
    return readArchmindSettings();
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(next: ArchmindSettings): ArchmindSettings {
  writeArchmindSettings(next);
  return next;
}

export function buildCreateDefaults(settings: ArchmindSettings): {
  template: ArchmindSettings["defaultTemplate"];
  mode: ArchmindSettings["defaultMode"];
  language: ArchmindSettings["defaultLanguage"];
  llmMode: ArchmindSettings["defaultLLM"];
} {
  return {
    template: settings.defaultTemplate,
    mode: settings.defaultMode,
    language: settings.defaultLanguage,
    llmMode: settings.defaultLLM,
  };
}
