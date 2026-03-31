"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

type Props = {
  projectName?: string;
};

type RunState = "idle" | "running" | "success" | "error";

type ConsoleResult = {
  command: string;
  status: "OK" | "FAILED" | "UNKNOWN";
  summary: string;
};

function normalizeCommand(value: string): string {
  return String(value || "").trim();
}

function extractSummary(payload: { detail?: unknown; error?: unknown }): string {
  const detail = String(payload.detail || "").trim();
  const error = String(payload.error || "").trim();
  return detail || error || "No summary available";
}

export default function CommandConsole({ projectName }: Props) {
  const router = useRouter();
  const [runState, setRunState] = useState<RunState>("idle");
  const [commandInput, setCommandInput] = useState("");
  const [validation, setValidation] = useState("");
  const [result, setResult] = useState<ConsoleResult | null>(null);
  const [inlineError, setInlineError] = useState("");
  const [recoveryHint, setRecoveryHint] = useState("");

  const targetProject = String(projectName || "").trim();
  const normalizedInput = normalizeCommand(commandInput);
  const canRun = Boolean(targetProject) && runState !== "running";

  async function runCommand() {
    const command = normalizeCommand(commandInput);
    if (!command) {
      setValidation("Enter a command.");
      return;
    }
    setValidation("");
    setInlineError("");
    setRecoveryHint("");
    setRunState("running");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        command?: string;
      };
      const ok = Boolean(payload.ok) && response.ok;
      const summary = extractSummary(payload);
      const resultCommand = normalizeCommand(String(payload.command || "")) || command;
      setResult({
        command: resultCommand,
        status: ok ? "OK" : "FAILED",
        summary,
      });
      setRunState(ok ? "success" : "error");
      if (ok) {
        router.refresh();
      } else {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: "Command execution",
          includeLogsHint: true,
        });
        setInlineError(classified.message);
        setRecoveryHint(classified.hint);
      }
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Command execution",
        includeLogsHint: true,
      });
      setResult({
        command,
        status: "FAILED",
        summary: classified.message || "No summary available",
      });
      setInlineError(classified.message);
      setRecoveryHint(classified.hint);
      setRunState("error");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canRun) {
      return;
    }
    void runCommand();
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Command Console</h3>
      <form className="mt-3 flex gap-2" onSubmit={handleSubmit}>
        <input
          type="text"
          value={commandInput}
          onChange={(event) => setCommandInput(event.target.value)}
          disabled={!canRun}
          placeholder="Enter command (e.g. /add_api GET /boards/{id}/cards)"
          className="w-full rounded-md border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!canRun || !normalizedInput}
          className="shrink-0 rounded-md border border-cyan-600 px-3 py-2 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {runState === "running" ? "Running..." : "Execute"}
        </button>
      </form>
      {validation ? <p className="mt-2 text-xs text-amber-300">{validation}</p> : null}
      {inlineError ? <p className="mt-2 text-xs text-rose-300">{inlineError}</p> : null}
      {recoveryHint ? <p className="mt-2 text-xs text-cyan-300">{recoveryHint}</p> : null}
      {result ? (
        <div className="mt-3 rounded-md border border-slate-700 bg-slate-950/70 p-3 text-xs text-slate-200">
          <p className="break-all">Command: {result.command}</p>
          <p className={result.status === "OK" ? "text-emerald-300" : result.status === "FAILED" ? "text-rose-300" : "text-slate-300"}>
            Status: {result.status}
          </p>
          <p className="break-words text-slate-300">Summary: {result.summary || "No summary available"}</p>
        </div>
      ) : null}
    </section>
  );
}
