"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type AutoStrategy = "safe" | "balanced" | "aggressive";

type AutoSummary = {
  run_id?: string;
  strategy?: AutoStrategy | string;
  executed?: number;
  commands?: string[];
  stop_reason?: string;
  stop_explanation?: string;
  plan_goal?: string;
  plan_reason?: string;
  planned_steps?: Array<{ command?: string; priority?: string; kind?: string }>;
  executed_steps?: Array<{ command?: string; priority?: string; goal?: string }>;
  skipped_steps?: Array<{ command?: string; reason?: string }>;
  goal_satisfied?: boolean;
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
  const initialStrategyRaw = String((autoSummary && typeof autoSummary === "object" ? autoSummary.strategy : "") || "")
    .trim()
    .toLowerCase();
  const initialStrategy: AutoStrategy =
    initialStrategyRaw === "safe" || initialStrategyRaw === "aggressive" || initialStrategyRaw === "balanced"
      ? (initialStrategyRaw as AutoStrategy)
      : "balanced";
  const [runState, setRunState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState<AutoStrategy>(initialStrategy);
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
  const planGoal = String(display.plan_goal || "").trim();
  const planReason = String(display.plan_reason || "").trim();
  const goalSatisfiedRaw = display.goal_satisfied;
  const goalSatisfied = typeof goalSatisfiedRaw === "boolean" ? (goalSatisfiedRaw ? "yes" : "no") : "";
  const plannedSteps = Array.isArray(display.planned_steps)
    ? display.planned_steps
        .map((item) => (item && typeof item === "object" ? String(item.command || "").trim() : ""))
        .filter((item) => item.length > 0)
    : [];
  const executedStepCommands = Array.isArray(display.executed_steps)
    ? display.executed_steps
        .map((item) => (item && typeof item === "object" ? String(item.command || "").trim() : ""))
        .filter((item) => item.length > 0)
    : [];
  const skippedStepCommands = Array.isArray(display.skipped_steps)
    ? display.skipped_steps
        .map((item) => (item && typeof item === "object" ? String(item.command || "").trim() : ""))
        .filter((item) => item.length > 0)
    : [];
  const strategy = String(display.strategy || "").trim().toLowerCase() || selectedStrategy;
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
    plannedSteps.length > 0 ||
    executedStepCommands.length > 0 ||
    skippedStepCommands.length > 0 ||
    Boolean(planGoal) ||
    Boolean(planReason) ||
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
        body: JSON.stringify({ command: "/auto", strategy: selectedStrategy }),
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
        const nextStrategy = String(payload.auto_result.strategy || "").trim().toLowerCase();
        if (nextStrategy === "safe" || nextStrategy === "balanced" || nextStrategy === "aggressive") {
          setSelectedStrategy(nextStrategy);
        }
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
        <label className="text-xs text-slate-300" htmlFor="auto-strategy">
          Strategy
        </label>
        <select
          id="auto-strategy"
          value={selectedStrategy}
          onChange={(event) => setSelectedStrategy(event.target.value as AutoStrategy)}
          disabled={runState === "running"}
          className="rounded-md border border-slate-600 bg-slate-950 px-2 py-1.5 text-xs text-slate-100 disabled:opacity-60"
        >
          <option value="safe">Safe</option>
          <option value="balanced">Balanced</option>
          <option value="aggressive">Aggressive</option>
        </select>
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
            <p>Strategy: {strategy}</p>
            {planGoal ? <p>Plan Goal: {planGoal}</p> : null}
            {planReason ? <p>Plan Reason: {planReason}</p> : null}
            <p>Executed: {executed}</p>
            <p>Commands: {commands.length ? commands.join(", ") : "(none)"}</p>
            {plannedSteps.length ? (
              <div>
                <p>Planned Steps:</p>
                <ol className="ml-4 list-decimal space-y-0.5">
                  {plannedSteps.map((step, index) => (
                    <li key={`${index}-${step}`}>{step}</li>
                  ))}
                </ol>
              </div>
            ) : null}
            {executedStepCommands.length ? (
              <p>Executed Steps: {executedStepCommands.join(", ")}</p>
            ) : null}
            {skippedStepCommands.length ? (
              <p>Skipped Steps: {skippedStepCommands.join(", ")}</p>
            ) : null}
            {goalSatisfied ? <p>Goal satisfied: {goalSatisfied}</p> : null}
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
