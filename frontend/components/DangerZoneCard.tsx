"use client";

import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";
import { useState } from "react";

type Props = {
  projectName?: string;
  repositoryUrl?: string;
};

type DeletePayload = {
  ok?: boolean;
  action?: string;
  project_name?: string;
  local_deleted?: boolean;
  github_deleted?: boolean;
  runtime_stopped?: boolean;
  detail?: string;
  error?: string;
};


export default function DangerZoneCard({ projectName, repositoryUrl }: Props) {
  const router = useRouter();
  const [loadingAction, setLoadingAction] = useState("");
  const [error, setError] = useState("");

  const repoLabel = resolveRepoLabel(repositoryUrl);

  async function runStopProject() {
    if (!projectName) {
      setError("Project name is missing");
      return;
    }
    if (!window.confirm(`Stop runtime for "${projectName}"?`)) {
      return;
    }
    await runAction("stop", "stop");
  }

  async function runDeleteLocal() {
    if (!projectName) {
      setError("Project name is missing");
      return;
    }
    if (!window.confirm(`Delete local project "${projectName}"?\nGitHub repo will not be deleted.`)) {
      return;
    }
    const payload = await runAction("delete-local", "delete-local");
    if (payload?.ok && payload.local_deleted) {
      router.push("/dashboard");
      router.refresh();
    }
  }

  async function runDeleteRepo() {
    if (!projectName) {
      setError("Project name is missing");
      return;
    }
    const expected = "DELETE";
    const typed = window.prompt(
      `Delete GitHub repo ${repoLabel}?\nType ${expected} to continue.\nLocal project files will remain.`,
      "",
    );
    if (typed !== expected) {
      setError("GitHub delete cancelled");
      return;
    }
    await runAction("delete-repo", "delete-repo");
  }

  async function runDeleteAll() {
    if (!projectName) {
      setError("Project name is missing");
      return;
    }
    const typedProject = window.prompt(`Type project name "${projectName}" to confirm combined delete.`, "");
    if (typedProject !== projectName) {
      setError("Combined delete cancelled");
      return;
    }
    const typedDelete = window.prompt("Type DELETE to remove local project and GitHub repo.", "");
    if (typedDelete !== "DELETE") {
      setError("Combined delete cancelled");
      return;
    }
    const payload = await runAction("delete-all", "delete-all");
    if (payload?.ok && payload.local_deleted) {
      router.push("/dashboard");
      router.refresh();
    }
  }

  async function runAction(path: string, actionLabel: string): Promise<DeletePayload | null> {
    if (!projectName) {
      setError("Project name is missing");
      return null;
    }
    setError("");
    setLoadingAction(actionLabel);
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(projectName)}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const payload = (await readJsonSafely(response)) as DeletePayload | null;
      if (!response.ok || (payload && payload.ok === false)) {
        setError(buildDeleteError(payload, response.status));
        return payload;
      }
      router.refresh();
      return payload;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Action failed: ${message}`);
      return null;
    } finally {
      setLoadingAction("");
    }
  }

  return (
    <section className="rounded-md border border-rose-700 bg-rose-950/30 p-4">
      <h3 className="text-sm font-semibold text-rose-200">Danger Zone</h3>
      <p className="mt-2 text-xs text-rose-100/80">Destructive actions are separated by scope. Local delete does not delete GitHub repo.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={runStopProject}
          disabled={Boolean(loadingAction)}
          className="rounded-md border border-amber-500 bg-amber-900/40 px-3 py-1.5 text-sm text-amber-100 hover:bg-amber-800/60 disabled:opacity-60"
        >
          {loadingAction === "stop" ? "Stop Project..." : "Stop Project"}
        </button>
        <button
          type="button"
          onClick={runDeleteLocal}
          disabled={Boolean(loadingAction)}
          className="rounded-md border border-rose-500 bg-rose-900/50 px-3 py-1.5 text-sm text-rose-100 hover:bg-rose-800/70 disabled:opacity-60"
        >
          {loadingAction === "delete-local" ? "Delete Local..." : "Delete Local Project"}
        </button>
        <button
          type="button"
          onClick={runDeleteRepo}
          disabled={Boolean(loadingAction)}
          className="rounded-md border border-rose-500 bg-rose-900/50 px-3 py-1.5 text-sm text-rose-100 hover:bg-rose-800/70 disabled:opacity-60"
        >
          {loadingAction === "delete-repo" ? "Delete Repo..." : "Delete GitHub Repo"}
        </button>
        <button
          type="button"
          onClick={runDeleteAll}
          disabled={Boolean(loadingAction)}
          className="rounded-md border border-rose-400 bg-rose-800 px-3 py-1.5 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-60"
        >
          {loadingAction === "delete-all" ? "Delete All..." : "Delete Project + GitHub Repo"}
        </button>
      </div>
      {error ? <p className="mt-2 whitespace-pre-wrap break-words text-xs text-rose-200">{error}</p> : null}
    </section>
  );
}

function resolveRepoLabel(repositoryUrl?: string): string {
  const raw = String(repositoryUrl || "").trim();
  if (!raw) {
    return "(unknown repo)";
  }
  const normalized = raw.replace(/\.git$/i, "");
  const parts = normalized.split("/");
  if (parts.length >= 2) {
    return `${parts[parts.length - 2]}/${parts[parts.length - 1]}`;
  }
  return normalized;
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

function buildDeleteError(payload: DeletePayload | null, status: number): string {
  const detail = String(payload?.detail || "").trim();
  const error = String(payload?.error || "").trim();
  const summary = detail || error || `HTTP ${status}`;
  if (detail && error && detail !== error) {
    return `${detail}\n${error}`;
  }
  return summary;
}
