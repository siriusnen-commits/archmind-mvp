"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

type NextCandidate = {
  command?: string;
  gap_type?: string;
  priority?: string;
  reason?: string;
  reason_summary?: string;
  expected_effect?: string;
};

type Props = {
  projectName?: string;
  candidates?: NextCandidate[];
};

type MessageType = "success" | "error";
type RunState = "idle" | "running" | "success" | "error";

function normalizeCommandText(value: string): string {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const singleLine = raw.split(/\r?\n/, 1)[0] || "";
  const withoutLabel = singleLine.replace(/^command:\s*/i, "").trim();
  return withoutLabel.replace(/^`|`$/g, "").trim();
}

function commandKey(command: string): string {
  return normalizeCommandText(command).toLowerCase();
}

export default function NextCandidatesCard({ projectName, candidates }: Props) {
  const router = useRouter();
  const [runningKey, setRunningKey] = useState("");
  const [runStateByCommand, setRunStateByCommand] = useState<Record<string, RunState>>({});
  const [messageByCommand, setMessageByCommand] = useState<Record<string, string>>({});
  const [messageTypeByCommand, setMessageTypeByCommand] = useState<Record<string, MessageType>>({});
  const [hintByCommand, setHintByCommand] = useState<Record<string, string>>({});
  const [executedCommand, setExecutedCommand] = useState("");

  const rows = (Array.isArray(candidates) ? candidates : [])
    .filter((item): item is NextCandidate => Boolean(item && typeof item === "object"))
    .map((item) => ({
      command: normalizeCommandText(String(item.command || "")),
      gapType: String(item.gap_type || "").trim() || "general_improvement",
      priority: String(item.priority || "").trim().toLowerCase() || "medium",
      reason: String(item.reason || item.reason_summary || "").trim() || "No reason available.",
      expectedEffect: String(item.expected_effect || "").trim() || "Improves project completeness in the next iteration.",
    }))
    .filter((item) => Boolean(item.command))
    .slice(0, 3);

  async function runCandidate(command: string) {
    const targetProject = String(projectName || "").trim();
    const normalizedCommand = normalizeCommandText(command);
    const key = commandKey(normalizedCommand);
    if (!targetProject || !normalizedCommand || !key) {
      return;
    }

    setRunningKey(key);
    setExecutedCommand(normalizedCommand);
    setRunStateByCommand((prev) => ({ ...prev, [key]: "running" }));
    setMessageByCommand((prev) => ({ ...prev, [key]: "" }));
    setHintByCommand((prev) => ({ ...prev, [key]: "" }));
    setMessageTypeByCommand((prev) => ({ ...prev, [key]: "success" }));
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
          actionLabel: "Next candidate run",
          includeLogsHint: true,
        });
        setRunStateByCommand((prev) => ({ ...prev, [key]: "error" }));
        setMessageTypeByCommand((prev) => ({ ...prev, [key]: "error" }));
        setMessageByCommand((prev) => ({
          ...prev,
          [key]: classified.message,
        }));
        setHintByCommand((prev) => ({ ...prev, [key]: classified.hint }));
        return;
      }
      const detail = String(payload.error || payload.detail || "").trim();
      setRunStateByCommand((prev) => ({ ...prev, [key]: "success" }));
      setMessageTypeByCommand((prev) => ({ ...prev, [key]: "success" }));
      setMessageByCommand((prev) => ({ ...prev, [key]: detail || "Completed" }));
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Next candidate run",
        includeLogsHint: true,
      });
      setRunStateByCommand((prev) => ({ ...prev, [key]: "error" }));
      setMessageTypeByCommand((prev) => ({ ...prev, [key]: "error" }));
      setMessageByCommand((prev) => ({ ...prev, [key]: classified.message }));
      setHintByCommand((prev) => ({ ...prev, [key]: classified.hint }));
    } finally {
      setRunningKey("");
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Next Candidates</h3>
      {!rows.length ? <p className="mt-2 text-sm text-slate-300">No recommended next step right now.</p> : null}
      {rows.length ? (
        <div className="mt-3 space-y-3">
          {rows.map((row, idx) => {
            const key = commandKey(row.command);
            const runState = runStateByCommand[key] || "idle";
            const isRunning = runningKey === key;
            const disabled = !Boolean(String(projectName || "").trim()) || Boolean(runningKey) || !Boolean(row.command);
            const message = String(messageByCommand[key] || "").trim();
            const hint = String(hintByCommand[key] || "").trim();
            const messageType = messageTypeByCommand[key] || "success";
            return (
              <article key={`${row.command}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                <p className="break-all text-sm font-semibold text-cyan-200">{row.command}</p>
                <p className="mt-2 text-xs text-slate-200">{row.reason}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className="inline-flex rounded-full border border-amber-500/60 bg-amber-900/30 px-2 py-0.5 text-[11px] text-amber-200">
                    {row.priority}
                  </span>
                  <span className="inline-flex rounded-full border border-slate-500 bg-slate-800/70 px-2 py-0.5 text-[11px] text-slate-200">
                    {row.gapType}
                  </span>
                </div>
                <p className="mt-2 text-[11px] text-slate-400">{row.expectedEffect}</p>
                <button
                  type="button"
                  onClick={() => runCandidate(row.command)}
                  disabled={disabled}
                  className="mt-3 rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
                >
                  {isRunning || runState === "running" ? "Running..." : runState === "success" ? "Completed" : "Run"}
                </button>
                {message ? (
                  <p className={messageType === "error" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>
                    {message}
                  </p>
                ) : null}
                {hint ? <p className="mt-1 text-xs text-cyan-300">{hint}</p> : null}
              </article>
            );
          })}
        </div>
      ) : null}
      {executedCommand ? <p className="mt-3 break-all text-xs text-slate-300">Executed: {executedCommand}</p> : null}
    </section>
  );
}
