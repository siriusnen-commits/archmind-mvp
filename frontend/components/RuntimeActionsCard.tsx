"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type Props = {
  projectName?: string;
};

type RuntimeAction = {
  path: "run-backend" | "run-all" | "restart" | "stop";
  label: string;
};

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
      setError("Failed to run action: project name is missing");
      return;
    }
    setError("");
    setLoadingAction(action.path);
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(projectName)}/${action.path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const payload = (await readJsonSafely(response)) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        status?: string;
      } | null;
      if (!response.ok) {
        setError(buildActionError(payload, response.status));
        return;
      }
      if (payload && payload.ok === false) {
        setError(buildActionError(payload, response.status));
        return;
      }
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Failed to run action: ${message}`);
    } finally {
      setLoadingAction("");
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Actions</h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {ACTIONS.map((action) => (
          <button
            key={action.path}
            type="button"
            disabled={loadingAction.length > 0}
            onClick={() => runAction(action)}
            className="rounded-md border border-slate-500 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-700 disabled:opacity-60"
          >
            {loadingAction === action.path ? `${action.label}...` : action.label}
          </button>
        ))}
      </div>
      {error ? <p className="mt-2 whitespace-pre-wrap break-words text-xs text-rose-300">{error}</p> : null}
    </section>
  );
}

async function readJsonSafely(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function buildActionError(payload: { detail?: string; error?: string } | null, status: number): string {
  const detail = String(payload?.detail || "").trim();
  const error = String(payload?.error || "").trim();
  const summary = detail || error || `HTTP ${status}`;
  if (detail && error && detail !== error) {
    return `Failed to run action: ${detail}\n${error}`;
  }
  return `Failed to run action: ${summary}`;
}
