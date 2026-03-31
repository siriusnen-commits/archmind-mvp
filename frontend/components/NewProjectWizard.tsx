"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type TemplateOption = "auto" | "diary" | "todo" | "kanban" | "bookmark";
type ModeOption = "fast" | "balanced" | "high_quality";
type LanguageOption = "english" | "korean" | "japanese";
type LlmModeOption = "local" | "cloud" | "hybrid";

type WizardResponse = {
  ok?: boolean;
  project_name?: string;
  detail?: string;
  error?: string;
};

const SETTINGS_KEYS = {
  mode: ["archmind.settings.generation_mode", "archmind.settings.generationMode"],
  language: ["archmind.settings.project_language", "archmind.settings.projectLanguage"],
  llmMode: ["archmind.settings.llm_mode", "archmind.settings.llmMode"],
} as const;

function readLocalDefault(keys: readonly string[]): string {
  if (typeof window === "undefined") {
    return "";
  }
  for (const key of keys) {
    try {
      const value = String(window.localStorage.getItem(key) || "").trim();
      if (value) return value;
    } catch {
      continue;
    }
  }
  return "";
}

export default function NewProjectWizard() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [idea, setIdea] = useState("");
  const [template, setTemplate] = useState<TemplateOption>("auto");
  const [mode, setMode] = useState<ModeOption>("balanced");
  const [language, setLanguage] = useState<LanguageOption>("english");
  const [llmMode, setLlmMode] = useState<LlmModeOption>("local");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [defaultsLoaded, setDefaultsLoaded] = useState(false);

  useEffect(() => {
    if (!open || defaultsLoaded || typeof window === "undefined") {
      return;
    }
    const rawMode = readLocalDefault(SETTINGS_KEYS.mode).toLowerCase();
    const rawLanguage = readLocalDefault(SETTINGS_KEYS.language).toLowerCase();
    const rawLlmMode = readLocalDefault(SETTINGS_KEYS.llmMode).toLowerCase();
    if (rawMode === "fast" || rawMode === "balanced" || rawMode === "high_quality") setMode(rawMode);
    if (rawLanguage === "english" || rawLanguage === "korean" || rawLanguage === "japanese") setLanguage(rawLanguage);
    if (rawLlmMode === "local" || rawLlmMode === "cloud" || rawLlmMode === "hybrid") setLlmMode(rawLlmMode);
    setDefaultsLoaded(true);
  }, [open, defaultsLoaded]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    const trimmedIdea = idea.trim();
    if (!trimmedIdea) {
      setError("Idea is required.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/idea_local`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idea: trimmedIdea,
          template,
          mode,
          language,
          llm_mode: llmMode,
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as WizardResponse;
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        setError(detail ? `Failed to generate: ${detail}` : "Failed to generate project.");
        return;
      }
      const name = String(payload.project_name || "").trim();
      if (!name) {
        setError("Generation started but project name is missing.");
        return;
      }
      setOpen(false);
      router.push(`/projects/${encodeURIComponent(name)}`);
      router.refresh();
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Failed to generate: ${detail}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm font-medium text-cyan-200 hover:bg-cyan-900/30"
      >
        New Project
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-xl rounded-lg border border-slate-700 bg-slate-900 p-4 sm:p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-slate-100">New Project</h2>
              <button
                type="button"
                onClick={() => {
                  if (!loading) setOpen(false);
                }}
                disabled={loading}
                className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-60"
              >
                Close
              </button>
            </div>
            <form onSubmit={onSubmit} className="space-y-3">
              <label className="block space-y-1">
                <span className="text-xs text-slate-300">Idea</span>
                <textarea
                  required
                  value={idea}
                  onChange={(event) => setIdea(event.target.value)}
                  placeholder={"personal diary app\ntodo app with deadlines\nbookmark manager with tags"}
                  rows={4}
                  disabled={loading}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
                />
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-slate-300">Template</span>
                <select
                  value={template}
                  onChange={(event) => setTemplate(event.target.value as TemplateOption)}
                  disabled={loading}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
                >
                  <option value="auto">auto</option>
                  <option value="diary">diary</option>
                  <option value="todo">todo</option>
                  <option value="kanban">kanban</option>
                  <option value="bookmark">bookmark</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-slate-300">Generation Mode</span>
                <select
                  value={mode}
                  onChange={(event) => setMode(event.target.value as ModeOption)}
                  disabled={loading}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
                >
                  <option value="fast">Fast</option>
                  <option value="balanced">Balanced</option>
                  <option value="high_quality">High Quality</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-slate-300">Project Language</span>
                <select
                  value={language}
                  onChange={(event) => setLanguage(event.target.value as LanguageOption)}
                  disabled={loading}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
                >
                  <option value="english">English</option>
                  <option value="korean">Korean</option>
                  <option value="japanese">Japanese</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="text-xs text-slate-300">LLM Mode</span>
                <select
                  value={llmMode}
                  onChange={(event) => setLlmMode(event.target.value as LlmModeOption)}
                  disabled={loading}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
                >
                  <option value="local">Local</option>
                  <option value="cloud">Cloud</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </label>

              {error ? <p className="text-xs text-rose-300">{error}</p> : null}

              <div className="pt-1">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full rounded-md border border-emerald-600 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60"
                >
                  {loading ? "Generating..." : "Generate Project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
