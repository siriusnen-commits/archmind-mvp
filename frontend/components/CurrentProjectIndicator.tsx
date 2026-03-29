"use client";

import { useEffect, useMemo, useState } from "react";
import { UI_API_BASE } from "@/components/uiApi";

type Props = {
  projectName?: string;
  displayName?: string;
  setOnMount?: boolean;
  className?: string;
};

const CURRENT_PROJECT_STORAGE_KEY = "archmind.currentProject";

export default function CurrentProjectIndicator({ projectName, displayName, setOnMount = false, className = "" }: Props) {
  const normalizedProjectName = String(projectName || "").trim();
  const normalizedDisplayName = String(displayName || normalizedProjectName || "").trim();
  const [storedProject, setStoredProject] = useState("");
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    try {
      const saved = String(localStorage.getItem(CURRENT_PROJECT_STORAGE_KEY) || "").trim();
      setStoredProject(saved);
    } catch {
      setStoredProject("");
    }
  }, []);

  useEffect(() => {
    if (!normalizedProjectName) {
      return;
    }
    try {
      localStorage.setItem(CURRENT_PROJECT_STORAGE_KEY, normalizedProjectName);
    } catch {
      // ignore localStorage errors
    }
    setStoredProject(normalizedProjectName);
  }, [normalizedProjectName]);

  useEffect(() => {
    if (!setOnMount || !normalizedProjectName) {
      return;
    }
    let cancelled = false;
    async function syncCurrentProject() {
      setIsSyncing(true);
      try {
        await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(normalizedProjectName)}/select`, { method: "POST" });
      } catch {
        // keep UI stable even if selection sync fails
      } finally {
        if (!cancelled) {
          setIsSyncing(false);
        }
      }
    }
    void syncCurrentProject();
    return () => {
      cancelled = true;
    };
  }, [setOnMount, normalizedProjectName]);

  const effectiveName = useMemo(() => normalizedDisplayName || storedProject || "(none)", [normalizedDisplayName, storedProject]);
  const effectiveId = useMemo(() => normalizedProjectName || storedProject || "", [normalizedProjectName, storedProject]);

  return (
    <section className={`rounded-md border border-cyan-700 bg-cyan-950/30 p-3 ${className}`.trim()}>
      <p className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Current Project Context</p>
      <p className="mt-1 break-all text-sm font-medium text-cyan-100">Current Project: {effectiveName}</p>
      <p className="mt-1 break-all text-xs text-cyan-300">ID: {effectiveId || "(none)"}</p>
      <p className="mt-1 text-xs text-cyan-300">
        {isSyncing ? "Syncing current project..." : "Commands from this view apply to this project context."}
      </p>
    </section>
  );
}
