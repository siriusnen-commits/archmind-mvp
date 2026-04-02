"use client";

import SettingsForm from "@/components/settings/SettingsForm";
import { loadSettings, saveSettings } from "@/lib/api/settings";
import type { ArchmindSettings } from "@/types/settings";
import { useEffect, useState } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function SettingsDrawer({ open, onClose }: Props) {
  const [settings, setSettings] = useState<ArchmindSettings>(() => loadSettings());
  const [savedAt, setSavedAt] = useState(0);

  useEffect(() => {
    if (!open) {
      return;
    }
    // Re-sync from persisted storage whenever the drawer opens so new settings fields are visible/useable.
    setSettings(loadSettings());
  }, [open]);

  if (!open) {
    return null;
  }

  function updateSettings(next: ArchmindSettings) {
    setSettings(next);
    saveSettings(next);
    setSavedAt(Date.now());
  }

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Settings">
      <button type="button" onClick={onClose} className="absolute inset-0 bg-slate-950/70" aria-label="Close settings" />
      <aside className="absolute bottom-0 left-0 top-0 w-full max-w-md overflow-y-auto border-r border-slate-700 bg-slate-900 p-4 sm:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-100">Settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Close
          </button>
        </div>
        <div data-testid="settings-content">
          <SettingsForm settings={settings} onChange={updateSettings} savedAt={savedAt} />
        </div>
      </aside>
    </div>
  );
}
