import type { ArchmindSettings } from "@/types/settings";

type Props = {
  settings: ArchmindSettings;
  onChange: (next: ArchmindSettings) => void;
  savedAt: number;
};

export default function SettingsForm({ settings, onChange, savedAt }: Props) {
  return (
    <div className="space-y-4">
      <section className="space-y-3 rounded-md border border-slate-700 bg-slate-950/40 p-3">
        <h3 className="text-sm font-semibold text-slate-100">Interface</h3>

        <label className="block space-y-1">
          <span className="text-xs text-slate-300">UI Language</span>
          <select
            value={settings.uiLanguage}
            onChange={(event) => onChange({ ...settings, uiLanguage: event.target.value as ArchmindSettings["uiLanguage"] })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          >
            <option value="en">English</option>
            <option value="ko">Korean</option>
            <option value="ja">Japanese</option>
          </select>
        </label>
      </section>

      <section className="space-y-3 rounded-md border border-slate-700 bg-slate-950/40 p-3">
        <h3 className="text-sm font-semibold text-slate-100">Generation Defaults</h3>

        <label className="block space-y-1">
          <span className="text-xs text-slate-300">Default Generation Mode</span>
          <select
            value={settings.defaultMode}
            onChange={(event) => onChange({ ...settings, defaultMode: event.target.value as ArchmindSettings["defaultMode"] })}
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
            onChange={(event) => onChange({ ...settings, defaultLanguage: event.target.value as ArchmindSettings["defaultLanguage"] })}
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
            onChange={(event) => onChange({ ...settings, defaultLLM: event.target.value as ArchmindSettings["defaultLLM"] })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          >
            <option value="local">Local</option>
            <option value="cloud">Cloud</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </label>
      </section>

      {savedAt > 0 ? <p className="text-xs text-emerald-300">Settings saved</p> : null}
    </div>
  );
}
