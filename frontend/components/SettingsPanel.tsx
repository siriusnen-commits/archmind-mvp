"use client";

import { useState } from "react";
import {
  ArchmindSettings,
  DEFAULT_SETTINGS,
  readArchmindSettings,
  writeArchmindSettings,
} from "@/components/settingsStore";

export default function SettingsPanel() {
  const [open, setOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [settings, setSettings] = useState<ArchmindSettings>(DEFAULT_SETTINGS);
  const [savedAt, setSavedAt] = useState(0);

  function updateSettings(next: ArchmindSettings) {
    setSettings(next);
    writeArchmindSettings(next);
    setSavedAt(Date.now());
  }

  function onOpen() {
    setSettings(readArchmindSettings());
    setOpen(true);
  }

  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        className="fixed bottom-4 left-4 z-40 inline-flex items-center gap-2 rounded-md border border-slate-600 bg-slate-900/90 px-3 py-2 text-sm text-slate-100 hover:bg-slate-800"
      >
        <span aria-hidden="true">[]</span>
        <span>Settings</span>
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-2xl rounded-lg border border-slate-700 bg-slate-900 p-4 sm:p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-slate-100">Settings</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
              >
                Close
              </button>
            </div>

            <div className="space-y-4">
                <section className="space-y-3 rounded-md border border-slate-700 bg-slate-950/40 p-3">
                  <h3 className="text-sm font-semibold text-slate-100">Interface</h3>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">UI Language</span>
                    <select
                      value={settings.uiLanguage}
                      onChange={(event) =>
                        updateSettings({ ...settings, uiLanguage: event.target.value as ArchmindSettings["uiLanguage"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="en">English</option>
                      <option value="ko">Korean</option>
                      <option value="ja">Japanese</option>
                    </select>
                  </label>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Layout Density</span>
                    <select
                      value={settings.layoutDensity}
                      onChange={(event) =>
                        updateSettings({ ...settings, layoutDensity: event.target.value as ArchmindSettings["layoutDensity"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="compact">Compact</option>
                      <option value="comfortable">Comfortable</option>
                    </select>
                  </label>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Preview Mode</span>
                    <select
                      value={settings.previewMode}
                      onChange={(event) =>
                        updateSettings({ ...settings, previewMode: event.target.value as ArchmindSettings["previewMode"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="auto">Auto</option>
                      <option value="desktop">Desktop</option>
                      <option value="mobile">Mobile</option>
                    </select>
                  </label>
                </section>

                <section className="space-y-3 rounded-md border border-slate-700 bg-slate-950/40 p-3">
                  <h3 className="text-sm font-semibold text-slate-100">Generation Defaults</h3>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Default Template</span>
                    <select
                      value={settings.defaultTemplate}
                      onChange={(event) =>
                        updateSettings({ ...settings, defaultTemplate: event.target.value as ArchmindSettings["defaultTemplate"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="auto">auto</option>
                      <option value="diary">diary</option>
                      <option value="todo">todo</option>
                      <option value="kanban">kanban</option>
                      <option value="bookmark">bookmark</option>
                    </select>
                  </label>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Default Generation Mode</span>
                    <select
                      value={settings.defaultMode}
                      onChange={(event) =>
                        updateSettings({ ...settings, defaultMode: event.target.value as ArchmindSettings["defaultMode"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="fast">Fast</option>
                      <option value="balanced">Balanced</option>
                      <option value="high_quality">High Quality</option>
                    </select>
                  </label>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Default Project Language</span>
                    <select
                      value={settings.defaultLanguage}
                      onChange={(event) =>
                        updateSettings({ ...settings, defaultLanguage: event.target.value as ArchmindSettings["defaultLanguage"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="english">English</option>
                      <option value="korean">Korean</option>
                      <option value="japanese">Japanese</option>
                    </select>
                  </label>

                  <label className="block space-y-1">
                    <span className="text-xs text-slate-300">Default LLM Mode</span>
                    <select
                      value={settings.defaultLLM}
                      onChange={(event) =>
                        updateSettings({ ...settings, defaultLLM: event.target.value as ArchmindSettings["defaultLLM"] })
                      }
                      className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
                    >
                      <option value="local">Local</option>
                      <option value="cloud">Cloud</option>
                      <option value="hybrid">Hybrid</option>
                    </select>
                  </label>
                </section>

                <section className="rounded-md border border-slate-700 bg-slate-950/40 p-3">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen((prev) => !prev)}
                    className="text-sm font-semibold text-slate-100 hover:text-cyan-200"
                  >
                    Advanced
                  </button>
                  {advancedOpen ? (
                    <div className="mt-3">
                      <label className="inline-flex items-center gap-2 text-sm text-slate-200">
                        <input
                          type="checkbox"
                          checked={settings.developerMode}
                          onChange={(event) =>
                            updateSettings({ ...settings, developerMode: event.target.checked })
                          }
                        />
                        Developer Mode
                      </label>
                    </div>
                  ) : null}
                </section>

                {savedAt > 0 ? <p className="text-xs text-emerald-300">Settings saved</p> : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
