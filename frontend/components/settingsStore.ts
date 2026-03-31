"use client";

export type UiLanguage = "en" | "ko" | "ja";
export type LayoutDensity = "compact" | "comfortable";
export type PreviewMode = "auto" | "desktop" | "mobile";
export type TemplateOption = "auto" | "diary" | "todo" | "kanban" | "bookmark";
export type GenerationMode = "fast" | "balanced" | "high_quality";
export type ProjectLanguage = "english" | "korean" | "japanese";
export type LlmMode = "local" | "cloud" | "hybrid";

export type ArchmindSettings = {
  uiLanguage: UiLanguage;
  layoutDensity: LayoutDensity;
  previewMode: PreviewMode;
  defaultTemplate: TemplateOption;
  defaultMode: GenerationMode;
  defaultLanguage: ProjectLanguage;
  defaultLLM: LlmMode;
  developerMode: boolean;
};

export const ARCHMIND_SETTINGS_KEY = "archmind.settings";

export const DEFAULT_SETTINGS: ArchmindSettings = {
  uiLanguage: "en",
  layoutDensity: "comfortable",
  previewMode: "auto",
  defaultTemplate: "auto",
  defaultMode: "balanced",
  defaultLanguage: "english",
  defaultLLM: "local",
  developerMode: false,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function pickString<T extends string>(
  raw: unknown,
  allowed: readonly T[],
  fallback: T
): T {
  const normalized = String(raw || "").trim().toLowerCase();
  return (allowed as readonly string[]).includes(normalized)
    ? (normalized as T)
    : fallback;
}

export function readArchmindSettings(): ArchmindSettings {
  if (typeof window === "undefined") {
    return { ...DEFAULT_SETTINGS };
  }
  const fallback = { ...DEFAULT_SETTINGS };
  try {
    const raw = window.localStorage.getItem(ARCHMIND_SETTINGS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (isRecord(parsed)) {
        fallback.uiLanguage = pickString(parsed.uiLanguage, ["en", "ko", "ja"], fallback.uiLanguage);
        fallback.layoutDensity = pickString(parsed.layoutDensity, ["compact", "comfortable"], fallback.layoutDensity);
        fallback.previewMode = pickString(parsed.previewMode, ["auto", "desktop", "mobile"], fallback.previewMode);
        fallback.defaultTemplate = pickString(parsed.defaultTemplate, ["auto", "diary", "todo", "kanban", "bookmark"], fallback.defaultTemplate);
        fallback.defaultMode = pickString(parsed.defaultMode, ["fast", "balanced", "high_quality"], fallback.defaultMode);
        fallback.defaultLanguage = pickString(parsed.defaultLanguage, ["english", "korean", "japanese"], fallback.defaultLanguage);
        fallback.defaultLLM = pickString(parsed.defaultLLM, ["local", "cloud", "hybrid"], fallback.defaultLLM);
        fallback.developerMode = Boolean(parsed.developerMode);
        return fallback;
      }
    }
  } catch {
    // fall through to legacy keys/defaults
  }

  // Legacy key fallback for compatibility.
  const legacyMode = String(window.localStorage.getItem("archmind.settings.generation_mode") || window.localStorage.getItem("archmind.settings.generationMode") || "").trim().toLowerCase();
  const legacyLanguage = String(window.localStorage.getItem("archmind.settings.project_language") || window.localStorage.getItem("archmind.settings.projectLanguage") || "").trim().toLowerCase();
  const legacyLlm = String(window.localStorage.getItem("archmind.settings.llm_mode") || window.localStorage.getItem("archmind.settings.llmMode") || "").trim().toLowerCase();

  fallback.defaultMode = pickString(legacyMode, ["fast", "balanced", "high_quality"], fallback.defaultMode);
  fallback.defaultLanguage = pickString(legacyLanguage, ["english", "korean", "japanese"], fallback.defaultLanguage);
  fallback.defaultLLM = pickString(legacyLlm, ["local", "cloud", "hybrid"], fallback.defaultLLM);
  return fallback;
}

export function writeArchmindSettings(next: ArchmindSettings): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(ARCHMIND_SETTINGS_KEY, JSON.stringify(next));
}
