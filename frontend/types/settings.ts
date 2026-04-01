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
