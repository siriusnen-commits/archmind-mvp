"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type AutoSummary = {
  run_id?: string;
  executed?: number;
  commands?: string[];
  stop_reason?: string;
  stop_explanation?: string;
  progress_made?: boolean;
  progress_score?: number;
  metrics_before?: Record<string, number>;
  metrics_after?: Record<string, number>;
  current?: string;
  runtime?: {
    backend_status?: string;
    frontend_status?: string;
    backend_url?: string;
    frontend_url?: string;
  };
};

type Props = {
  projectName?: string;
  autoSummary?: AutoSummary;
};

type RunState = "idle" | "running" | "success" | "error";

function metricValue(row: Record<string, number> | undefined, key: string): number {
  if (!row || typeof row !== "object") {
    return 0;
  }
  const raw = row[key];
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw;
  }
  return 0;
}

export default function AutoControlPanel({ projectName, autoSummary }: Props) {
  const router = useRouter();
  const [runState, setRunState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const [lastAutoResult, setLastAutoResult] = useState<AutoSummary | undefined>(
    autoSummary && typeof autoSummary === "object" ? autoSummary : undefined,
  );

  const display = useMemo(
    () => ((lastAutoResult && typeof lastAutoResult === "object" ? lastAutoResult : autoSummary) || {}),
    [autoSummary, lastAutoResult],
  );

  const commands = Array.isArray(display.commands)
    ? display.commands.map((item) => String(item || "").trim()).filter((item) => item.length > 0)
    : [];
  const executed = Number.isFinite(Number(display.executed)) ? Number(display.executed) : commands.length;
  const stopReason = String(display.stop_reason || "").trim();
  const stopExplanation = String(display.stop_explanation || "").trim();
  const progressMadeRaw = display.progress_made;
  const progressMade =
    typeof progressMadeRaw === "boolean" ? (progressMadeRaw ? "yes" : "no") : "";
  const progressScore = Number.isFinite(Number(display.progress_score)) ? Number(display.progress_score) : 0;
  const currentSummary = String(display.current || "").trim();
  const runtime = display.runtime && typeof display.runtime === "object" ? display.runtime : {};
  const backendStatus = String(runtime.backend_status || "").trim();
  const frontendStatus = String(runtime.frontend_status || "").trim();
  const backendUrl = String(runtime.backend_url || "").trim();
  const frontendUrl = String(runtime.frontend_url || "").trim();
  const hasSummary =
    Boolean(String(display.run_id || "").trim()) ||
    commands.length > 0 ||
    Boolean(stopReason) ||
    Boolean(stopExplanation) ||
    Boolean(currentSummary);
  const targetProject = String(projectName || "").trim();
  const canRun = Boolean(targetProject) && runState !== "running";

  async function runAuto() {
    if (!targetProject) {
      setRunState("error");
      setMessage("Failed to run auto: project name is missing");
      return;
    }
    setRunState("running");
    setMessage("");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/commands`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "/auto" }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        auto_result?: AutoSummary;
      };
      const detail = String(payload.error || payload.detail || "").trim();
      if (!response.ok || !Boolean(payload.ok)) {
        setRunState("error");
        setMessage(detail ? `Auto failed: ${detail}` : "Auto failed");
        return;
      }
      if (payload.auto_result && typeof payload.auto_result === "object") {
        setLastAutoResult(payload.auto_result);
      }
      setRunState("success");
      setMessage(detail || "Auto completed");
      router.refresh();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || "unknown error");
      setRunState("error");
      setMessage(`Auto failed: ${detail}`);
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Auto Control</h3>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={runAuto}
          disabled={!canRun}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {runState === "running" ? "Running Auto..." : "Run Auto"}
        </button>
        <button
          type="button"
          onClick={() => router.refresh()}
          disabled={runState === "running"}
          className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-60"
        >
          Refresh
        </button>
      </div>
      {message ? (
        <p className={runState === "error" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>{message}</p>
      ) : null}

      <div className="mt-4 rounded-md border border-slate-700 bg-slate-950/70 p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Latest Auto Result</p>
        {!hasSummary ? <p className="mt-2 text-xs text-slate-400">No auto run yet.</p> : null}
        {hasSummary ? (
          <div className="mt-2 space-y-1 text-xs text-slate-200">
            <p>Executed: {executed}</p>
            <p>Commands: {commands.length ? commands.join(", ") : "(none)"}</p>
            {stopReason ? <p>Stopped: {stopReason}</p> : null}
            {stopExplanation ? <p>Why stop: {stopExplanation}</p> : null}
            {progressMade ? <p>Progress made: {progressMade}</p> : null}
            <p>Progress score: {progressScore}</p>
            <p>
              Metrics: entities {metricValue(display.metrics_before, "entities")}→{metricValue(display.metrics_after, "entities")},{" "}
              apis {metricValue(display.metrics_before, "apis")}→{metricValue(display.metrics_after, "apis")},{" "}
              pages {metricValue(display.metrics_before, "pages")}→{metricValue(display.metrics_after, "pages")},{" "}
              relation_pages {metricValue(display.metrics_before, "relation_pages")}→{metricValue(display.metrics_after, "relation_pages")},{" "}
              relation_apis {metricValue(display.metrics_before, "relation_apis")}→{metricValue(display.metrics_after, "relation_apis")},{" "}
              placeholders {metricValue(display.metrics_before, "placeholders")}→{metricValue(display.metrics_after, "placeholders")}
            </p>
            {currentSummary ? <p>Current: {currentSummary}</p> : null}
            {(backendStatus || frontendStatus) ? <p>Runtime: backend={backendStatus || "unknown"}, frontend={frontendStatus || "unknown"}</p> : null}
            {backendUrl ? <p>Backend URL: {backendUrl}</p> : null}
            {frontendUrl ? <p>Frontend URL: {frontendUrl}</p> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

