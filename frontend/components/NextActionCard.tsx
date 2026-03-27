"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type NextAction = {
  kind?: string;
  message?: string;
  command?: string;
};

type Props = {
  projectName?: string;
  nextAction?: NextAction;
};

type MessageType = "success" | "info" | "error";
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

function isNoImmediate(nextAction: NextAction): boolean {
  const kind = String(nextAction.kind || "").trim().toLowerCase();
  const message = String(nextAction.message || "").trim().toLowerCase();
  return kind === "none" || !message || message === "no immediate suggestions.";
}

export default function NextActionCard({ projectName, nextAction }: Props) {
  const router = useRouter();
  const [runState, setRunState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<MessageType>("success");
  const [executedCommand, setExecutedCommand] = useState("");

  const action = nextAction || {};
  const noImmediate = isNoImmediate(action);
  const actionMessage = noImmediate ? "No immediate next action." : String(action.message || "").trim();
  const command = String(action.command || "").trim();
  const normalizedCommand = normalizeCommandText(command);
  const canRun = Boolean(normalizedCommand && !noImmediate && String(projectName || "").trim()) && runState !== "running" && runState !== "success";

  async function runNextAction() {
    const targetProject = String(projectName || "").trim();
    if (!targetProject) {
      setRunState("error");
      setMessageType("error");
      setMessage("Failed to run next action: project name is missing");
      return;
    }
    if (!normalizedCommand) {
      setRunState("error");
      setMessageType("error");
      setMessage("Failed to run next action: unsupported or invalid command");
      return;
    }

    setRunState("running");
    setMessage("");
    setExecutedCommand(normalizedCommand);
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
      const detail = String(payload.error || payload.detail || "").trim();

      if (!response.ok || !Boolean(payload.ok)) {
        if (detail.toLowerCase().includes("already exists")) {
          setRunState("success");
          setMessageType("info");
          setMessage("Already exists (auto-created)");
          return;
        }
        setRunState("error");
        setMessageType("error");
        setMessage(detail ? `Failed to run next action: ${detail}` : "Failed to run next action");
        return;
      }

      setRunState("success");
      setMessageType("success");
      setMessage(detail || "Completed");
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || "unknown error");
      setRunState("error");
      setMessageType("error");
      setMessage(`Failed to run next action: ${detail}`);
    }
  }

  function refreshSuggestions() {
    setRunState("idle");
    setMessage("");
    setExecutedCommand("");
    router.refresh();
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Next Action</h3>
      <p className="mt-2 break-words text-sm text-slate-200">{actionMessage}</p>
      {command ? <p className="mt-2 break-words text-xs text-cyan-300">Command: {command}</p> : null}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={runNextAction}
          disabled={!canRun}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {runState === "running" ? "Running..." : runState === "success" ? "Completed" : "Run"}
        </button>
        <button
          type="button"
          onClick={refreshSuggestions}
          disabled={runState === "running"}
          className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
        >
          Refresh suggestions
        </button>
      </div>
      {executedCommand ? <p className="mt-2 break-words text-xs text-slate-300">Executed: {executedCommand}</p> : null}
      {message ? (
        <p
          className={
            messageType === "error"
              ? "mt-2 break-words text-xs text-rose-300"
              : messageType === "info"
                ? "mt-2 break-words text-xs text-cyan-300"
                : "mt-2 break-words text-xs text-emerald-300"
          }
        >
          {message}
        </p>
      ) : null}
    </section>
  );
}
