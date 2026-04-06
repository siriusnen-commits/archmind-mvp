"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

type PlanStep = {
  title?: string;
  why?: string;
  command?: string;
};

type PlanOverview = {
  goal?: string;
  priority?: string;
  why?: string;
  expected_effect?: string;
  steps?: PlanStep[];
};

type Props = {
  projectName?: string;
  plan?: PlanOverview | null;
};

type RunState = "idle" | "running" | "success" | "error";

function normalizeCommand(value: string): string {
  return String(value || "").trim();
}

export default function PlanOverviewCard({ projectName, plan }: Props) {
  const router = useRouter();
  const [runningCommand, setRunningCommand] = useState("");
  const [runStateByCommand, setRunStateByCommand] = useState<Record<string, RunState>>({});
  const [messageByCommand, setMessageByCommand] = useState<Record<string, string>>({});
  const [hintByCommand, setHintByCommand] = useState<Record<string, string>>({});

  const row = plan && typeof plan === "object" ? plan : {};
  const goal = String(row.goal || "").trim();
  const priority = String(row.priority || "").trim();
  const why = String(row.why || "").trim();
  const expectedEffect = String(row.expected_effect || "").trim();
  const steps = (Array.isArray(row.steps) ? row.steps : [])
    .filter((item): item is PlanStep => Boolean(item && typeof item === "object"))
    .map((item) => ({
      title: String(item.title || "").trim() || "Plan step",
      why: String(item.why || "").trim(),
      command: normalizeCommand(String(item.command || "")),
    }));

  const hasAny = Boolean(goal || priority || why || expectedEffect || steps.length);

  async function copyCommand(command: string) {
    const value = normalizeCommand(command);
    if (!value) {
      return;
    }
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      }
    } catch {
      // no-op fallback; keep UI safe.
    }
  }

  async function runCommand(command: string) {
    const targetProject = String(projectName || "").trim();
    const normalizedCommand = normalizeCommand(command);
    if (!targetProject || !normalizedCommand) {
      return;
    }

    setRunningCommand(normalizedCommand);
    setRunStateByCommand((prev) => ({ ...prev, [normalizedCommand]: "running" }));
    setMessageByCommand((prev) => ({ ...prev, [normalizedCommand]: "" }));
    setHintByCommand((prev) => ({ ...prev, [normalizedCommand]: "" }));

    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: normalizedCommand }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: "Plan step run",
          includeLogsHint: true,
        });
        setRunStateByCommand((prev) => ({ ...prev, [normalizedCommand]: "error" }));
        setMessageByCommand((prev) => ({ ...prev, [normalizedCommand]: classified.message }));
        setHintByCommand((prev) => ({ ...prev, [normalizedCommand]: classified.hint }));
        return;
      }
      const detail = String(payload.error || payload.detail || "").trim();
      setRunStateByCommand((prev) => ({ ...prev, [normalizedCommand]: "success" }));
      setMessageByCommand((prev) => ({ ...prev, [normalizedCommand]: detail || "Completed" }));
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Plan step run",
        includeLogsHint: true,
      });
      setRunStateByCommand((prev) => ({ ...prev, [normalizedCommand]: "error" }));
      setMessageByCommand((prev) => ({ ...prev, [normalizedCommand]: classified.message }));
      setHintByCommand((prev) => ({ ...prev, [normalizedCommand]: classified.hint }));
    } finally {
      setRunningCommand("");
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Plan Overview</h3>
      {!hasAny ? <p className="mt-2 text-sm text-slate-300">No plan result yet. Run /plan to generate implementation steps.</p> : null}

      {hasAny ? (
        <div className="mt-3 space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Goal</p>
              <p className="mt-1 text-sm text-slate-200">{goal || "No goal available."}</p>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Priority</p>
              <p className="mt-1 text-sm text-slate-200">{priority || "No priority available."}</p>
            </div>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Why</p>
            <p className="mt-1 text-sm text-slate-200">{why || "No rationale available."}</p>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Expected Effect</p>
            <p className="mt-1 text-sm text-slate-200">{expectedEffect || "No expected effect available."}</p>
          </div>

          <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Steps</p>
            {steps.length === 0 ? <p className="mt-1 text-sm text-slate-300">No plan steps available.</p> : null}
            {steps.length > 0 ? (
              <div className="mt-2 space-y-2">
                {steps.slice(0, 20).map((step, idx) => {
                  const command = normalizeCommand(step.command || "");
                  const runState = runStateByCommand[command] || "idle";
                  const disabled = !command || !String(projectName || "").trim() || Boolean(runningCommand);
                  const message = String(messageByCommand[command] || "").trim();
                  const hint = String(hintByCommand[command] || "").trim();
                  return (
                    <article key={`${step.title}-${command}-${idx}`} className="rounded border border-slate-700 bg-slate-950/70 p-3">
                      <p className="text-sm font-semibold text-slate-100">{step.title || "Plan step"}</p>
                      <p className="mt-1 text-xs text-slate-300">{step.why || why || "No step rationale."}</p>
                      {command ? <p className="mt-2 break-all text-xs text-cyan-200">{command}</p> : <p className="mt-2 text-xs text-slate-400">No command</p>}
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          onClick={() => copyCommand(command)}
                          disabled={!command}
                          className="rounded-md border border-slate-500 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-60"
                        >
                          Copy
                        </button>
                        <button
                          type="button"
                          onClick={() => runCommand(command)}
                          disabled={disabled}
                          className="rounded-md border border-cyan-600 px-3 py-1.5 text-xs text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
                        >
                          {runState === "running" ? "Running..." : runState === "success" ? "Completed" : "Run"}
                        </button>
                      </div>
                      {message ? <p className={runState === "error" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>{message}</p> : null}
                      {hint ? <p className="mt-1 text-xs text-cyan-300">{hint}</p> : null}
                    </article>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
