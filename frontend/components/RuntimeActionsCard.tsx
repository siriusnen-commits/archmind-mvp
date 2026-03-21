"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Props = {
  projectName?: string;
};

type RuntimeAction = {
  path: "run-backend" | "run-all" | "restart" | "stop";
  label: string;
};

const API_BASE = "/api/ui";
const ACTIONS: RuntimeAction[] = [
  { path: "run-backend", label: "Run Backend" },
  { path: "run-all", label: "Run All" },
  { path: "restart", label: "Restart" },
  { path: "stop", label: "Stop" },
];

export default function RuntimeActionsCard({ projectName }: Props) {
  const router = useRouter();
  const [loadingAction, setLoadingAction] = useState<string>("");
  const [error, setError] = useState("");

  async function runAction(action: RuntimeAction) {
    if (!projectName) {
      setError("Failed to run action");
      return;
    }
    setError("");
    setLoadingAction(action.path);
    try {
      const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectName)}/${action.path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!response.ok) {
        setError("Failed to run action");
        return;
      }
      router.refresh();
    } catch {
      setError("Failed to run action");
    } finally {
      setLoadingAction("");
    }
  }

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-900">Actions</h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {ACTIONS.map((action) => (
          <button
            key={action.path}
            type="button"
            disabled={loadingAction.length > 0}
            onClick={() => runAction(action)}
            className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-800 hover:bg-zinc-50 disabled:opacity-60"
          >
            {loadingAction === action.path ? `${action.label}...` : action.label}
          </button>
        ))}
      </div>
      {error ? <p className="mt-2 text-xs text-red-600">{error}</p> : null}
    </section>
  );
}
