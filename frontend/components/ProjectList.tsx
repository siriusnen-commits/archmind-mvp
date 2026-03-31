"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

export type ProjectListItem = {
  name?: string;
  display_name?: string;
  path?: string;
  status?: string;
  runtime?: string;
  type?: string;
  template?: string;
  backend_url?: string;
  frontend_url?: string;
  backend_urls?: string[];
  frontend_urls?: string[];
  runtime_state?: string;
  repository?: {
    status?: string;
    url?: string;
  };
  project_health_status?: string;
  is_current?: boolean;
};

type Props = {
  projects: ProjectListItem[];
  selectedName?: string;
};

export default function ProjectList({ projects, selectedName }: Props) {
  const router = useRouter();
  const [settingCurrentName, setSettingCurrentName] = useState("");
  const [setCurrentError, setSetCurrentError] = useState("");
  const [runningCommandProject, setRunningCommandProject] = useState("");
  const [runningCommandLabel, setRunningCommandLabel] = useState("");
  const [commandFeedbackByProject, setCommandFeedbackByProject] = useState<Record<string, { status: "OK" | "FAILED"; message: string; hint?: string }>>({});

  async function handleSetCurrent(projectName: string) {
    const target = String(projectName || "").trim();
    if (!target) {
      return;
    }
    setSettingCurrentName(target);
    setSetCurrentError("");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(target)}/select`, {
        method: "POST",
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const classified = classifyActionFailure(response, payload, { actionLabel: "Set current project" });
        setSetCurrentError(classified.message);
        return;
      }
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, { actionLabel: "Set current project" });
      setSetCurrentError(classified.message);
    } finally {
      setSettingCurrentName("");
    }
  }

  async function runQuickCommand(projectName: string, command: "/auto" | "/fix") {
    const target = String(projectName || "").trim();
    if (!target) {
      return;
    }
    setRunningCommandProject(target);
    setRunningCommandLabel(command);
    setCommandFeedbackByProject((prev) => {
      const next = { ...prev };
      delete next[target];
      return next;
    });
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(target)}/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const payload = (await response.json().catch(() => ({}))) as { ok?: boolean; detail?: string; error?: string };
      if (!response.ok || !Boolean(payload.ok)) {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: `${command} execution`,
          includeLogsHint: true,
        });
        setCommandFeedbackByProject((prev) => ({
          ...prev,
          [target]: { status: "FAILED", message: classified.message, hint: classified.hint },
        }));
        return;
      }
      setCommandFeedbackByProject((prev) => ({
        ...prev,
        [target]: { status: "OK", message: detail || "Completed" },
      }));
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: `${command} execution`,
        includeLogsHint: true,
      });
      setCommandFeedbackByProject((prev) => ({
        ...prev,
        [target]: { status: "FAILED", message: classified.message, hint: classified.hint },
      }));
    } finally {
      setRunningCommandProject("");
      setRunningCommandLabel("");
    }
  }

  function normalizeBadge(status: string): "RUNNING" | "BROKEN" | "NEEDS FIX" | "IDLE" {
    const normalized = String(status || "").trim().toUpperCase();
    if (normalized === "RUNNING") {
      return "RUNNING";
    }
    if (normalized === "BROKEN") {
      return "BROKEN";
    }
    if (normalized === "NEEDS FIX") {
      return "NEEDS FIX";
    }
    return "IDLE";
  }

  function badgeClass(status: "RUNNING" | "BROKEN" | "NEEDS FIX" | "IDLE"): string {
    if (status === "RUNNING") {
      return "border-emerald-400 bg-emerald-900/50 text-emerald-200";
    }
    if (status === "BROKEN") {
      return "border-rose-400 bg-rose-900/50 text-rose-200";
    }
    if (status === "NEEDS FIX") {
      return "border-amber-400 bg-amber-900/50 text-amber-200";
    }
    return "border-slate-500 bg-slate-800/70 text-slate-200";
  }

  if (!projects.length) {
    return (
      <div className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">
        No projects found
      </div>
    );
  }

  return (
    <aside className="rounded-md border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">Projects</h2>
      <ul className="space-y-2">
        {projects.map((project) => {
          const name = String(project.name || "");
          const displayName = String(project.display_name || name || "(unknown)");
          const isCurrent = Boolean(project.is_current);
          const isSelected = Boolean(selectedName && selectedName === name);
          const repositoryUrl = String(project.repository?.url || "").trim();
          const healthStatus = normalizeBadge(String(project.project_health_status || ""));
          const feedback = commandFeedbackByProject[name];
          const isCommandRunning = runningCommandProject === name;
          return (
            <li key={name || displayName}>
              <div
                className={[
                  "rounded-md border px-3 py-2 transition",
                  isSelected
                    ? "border-cyan-500 bg-slate-800"
                    : "border-slate-700 bg-slate-900 hover:bg-slate-800",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <Link
                    href={name ? `/projects/${encodeURIComponent(name)}` : "/dashboard"}
                    className="break-all text-sm font-medium text-slate-100 underline-offset-2 hover:underline"
                  >
                    {displayName}
                  </Link>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${badgeClass(healthStatus)}`}>{healthStatus}</span>
                  {isCurrent ? (
                    <span className="rounded-full border border-emerald-400 bg-emerald-900/50 px-2 py-0.5 text-[11px] font-medium text-emerald-200">
                      CURRENT
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-all text-xs text-slate-300">ID: {name || "(unknown)"}</p>
                <p className="text-xs text-slate-300">Status: {String(project.status || "unknown")}</p>
                {name ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Link
                      href={`/projects/${encodeURIComponent(name)}`}
                      className="rounded-md border border-slate-500 px-2 py-1 text-xs text-slate-100 hover:bg-slate-800"
                    >
                      Open
                    </Link>
                    <Link
                      href={`/projects/${encodeURIComponent(name)}`}
                      className="rounded-md border border-cyan-600 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-900/30"
                    >
                      Inspect
                    </Link>
                    <button
                      type="button"
                      onClick={() => void runQuickCommand(name, "/auto")}
                      disabled={isCommandRunning}
                      className="rounded-md border border-violet-500 px-2 py-1 text-xs text-violet-200 hover:bg-violet-900/30 disabled:opacity-60"
                    >
                      Auto
                    </button>
                    <button
                      type="button"
                      onClick={() => void runQuickCommand(name, "/fix")}
                      disabled={isCommandRunning}
                      className="rounded-md border border-amber-500 px-2 py-1 text-xs text-amber-200 hover:bg-amber-900/30 disabled:opacity-60"
                    >
                      Fix
                    </button>
                  </div>
                ) : null}
                {isCommandRunning ? (
                  <p className="mt-1 text-xs text-cyan-300">Running... {runningCommandLabel || "command"}</p>
                ) : null}
                {feedback ? (
                  <div className={`mt-1 text-xs ${feedback.status === "OK" ? "text-emerald-300" : "text-rose-300"}`}>
                    <p>
                      {feedback.status}: {feedback.message}
                    </p>
                    {feedback.hint ? <p className="mt-1 text-cyan-300">{feedback.hint}</p> : null}
                  </div>
                ) : null}
                <div className="mt-2">
                  {isCurrent ? (
                    <p className="text-xs text-emerald-300">Current project</p>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleSetCurrent(name)}
                      disabled={settingCurrentName === name || isCommandRunning}
                      className="rounded-md border border-cyan-600 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-900/30"
                    >
                      {settingCurrentName === name ? "Setting..." : "Set current"}
                    </button>
                  )}
                </div>
                {settingCurrentName === name ? <p className="text-xs text-cyan-300">Setting current project...</p> : null}
                <div className="mt-1 text-xs text-slate-300">
                  Repository:{" "}
                  {repositoryUrl ? (
                    <a
                      href={repositoryUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-cyan-300 underline underline-offset-2 hover:text-cyan-200"
                    >
                      Open Repo
                    </a>
                  ) : (
                    <span>No repository</span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {setCurrentError ? <p className="mt-2 break-words text-xs text-rose-300">{setCurrentError}</p> : null}
    </aside>
  );
}
