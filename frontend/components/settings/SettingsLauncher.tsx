"use client";

import { useEffect, useState } from "react";

import SettingsDrawer from "@/components/settings/SettingsDrawer";

export default function SettingsLauncher() {
  const [open, setOpen] = useState(false);
  const [drawerVersion, setDrawerVersion] = useState(0);

  function openDrawer() {
    setDrawerVersion((prev) => prev + 1);
    setOpen(true);
  }

  useEffect(() => {
    function onOpenSettings() {
      setDrawerVersion((prev) => prev + 1);
      setOpen(true);
    }
    window.addEventListener("archmind:open-settings", onOpenSettings);
    return () => {
      window.removeEventListener("archmind:open-settings", onOpenSettings);
    };
  }, []);

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
