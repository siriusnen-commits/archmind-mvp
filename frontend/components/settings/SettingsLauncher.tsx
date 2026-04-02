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
        aria-label="Open settings"
        className="fixed bottom-4 left-4 z-40 inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-600 bg-slate-900/90 text-sm font-semibold text-slate-100 shadow-lg hover:bg-slate-800"
      >
        N
      </button>
      <SettingsDrawer key={drawerVersion} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
