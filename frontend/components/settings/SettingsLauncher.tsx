"use client";

import { useEffect, useState } from "react";

import SettingsDrawer from "@/components/settings/SettingsDrawer";

export default function SettingsLauncher() {
  const [enabled, setEnabled] = useState(true);
  const [open, setOpen] = useState(false);
  const [drawerVersion, setDrawerVersion] = useState(0);

  function openDrawer() {
    setDrawerVersion((prev) => prev + 1);
    setOpen(true);
  }

  useEffect(() => {
    const markerKey = "__archmind_settings_launcher_singleton__";
    const globalWindow = window as Window & { [key: string]: unknown };
    if (globalWindow[markerKey]) {
      setEnabled(false);
      return;
    }
    globalWindow[markerKey] = true;
    function onOpenSettings() {
      setDrawerVersion((prev) => prev + 1);
      setOpen(true);
    }
    window.addEventListener("archmind:open-settings", onOpenSettings);
    return () => {
      window.removeEventListener("archmind:open-settings", onOpenSettings);
      delete globalWindow[markerKey];
    };
  }, []);

  if (!enabled) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={openDrawer}
        data-testid="archmind-settings-launcher"
        aria-label="Open settings"
        className="fixed bottom-4 right-4 z-40 inline-flex items-center gap-2 rounded-full border border-slate-600 bg-slate-900/90 px-3 py-2 text-sm font-semibold text-slate-100 shadow-lg hover:bg-slate-800"
      >
        <span aria-hidden="true">[]</span>
        <span>Settings</span>
      </button>
      <SettingsDrawer key={drawerVersion} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
