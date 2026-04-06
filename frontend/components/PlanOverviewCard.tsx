"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

type PlanStep = {
  id?: string;
  title?: string;
  why?: string;
  command?: string;
  depends_on?: string[];
  expected_effect?: string;
  priority?: string;
  type?: string;
};

type PlanFlow = {
  name?: string;
  flow_type?: string;
  steps?: PlanStep[];
};

type PlanOverview = {
  goal?: string;
  priority?: string;
  why?: string;
  expected_effect?: string;
  flows?: PlanFlow[];
  steps?: PlanStep[];
};

type Props = {
  projectName?: string;
  plan?: PlanOverview | null;
};

type RunState = "idle" | "running" | "success" | "error";
type StepRunStatus = "pending" | "running" | "done" | "failed";

function normalizeCommand(value: string): string {
  return String(value || "").trim();
}

export default function PlanOverviewCard({ projectName, plan }: Props) {
  const router = useRouter();
  const [runningCommand, setRunningCommand] = useState("");
  const [runStateByCommand, setRunStateByCommand] = useState<Record<string, RunState>>({});
  const [messageByCommand, setMessageByCommand] = useState<Record<string, string>>({});
  const [hintByCommand, setHintByCommand] = useState<Record<string, string>>({});
  const [runningFlowKey, setRunningFlowKey] = useState("");
  const [flowStepStatusByKey, setFlowStepStatusByKey] = useState<Record<string, StepRunStatus>>({});
  const [flowMessageByStepKey, setFlowMessageByStepKey] = useState<Record<string, string>>({});
  const [flowHintByStepKey, setFlowHintByStepKey] = useState<Record<string, string>>({});
  const [flowSummaryByKey, setFlowSummaryByKey] = useState<Record<string, string>>({});
  const [flowRunningStepByKey, setFlowRunningStepByKey] = useState<Record<string, string>>({});

  const row = plan && typeof plan === "object" ? plan : {};
  const goal = String(row.goal || "").trim();
  const priority = String(row.priority || "").trim();
  const why = String(row.why || "").trim();
  const expectedEffect = String(row.expected_effect || "").trim();
  const flows = (Array.isArray(row.flows) ? row.flows : [])
    .filter((flow): flow is PlanFlow => Boolean(flow && typeof flow === "object"))
    .map((flow) => ({
      name: String(flow.name || "").trim() || "Plan Flow",
      flowType: String(flow.flow_type || "").trim().toLowerCase() || "crud",
      steps: (Array.isArray(flow.steps) ? flow.steps : [])
        .filter((item): item is PlanStep => Boolean(item && typeof item === "object"))
        .map((item) => ({
          id: String(item.id || "").trim(),
          title: String(item.title || "").trim() || "Plan step",
          command: normalizeCommand(String(item.command || "")),
          dependsOn: Array.isArray(item.depends_on)
            ? item.depends_on.map((dep) => String(dep || "").trim()).filter((dep) => Boolean(dep))
            : [],
          why: String(item.why || "").trim(),
          expectedEffect: String(item.expected_effect || "").trim(),
          priority: String(item.priority || "").trim().toLowerCase(),
          stepType: String(item.type || "").trim().toLowerCase(),
        }))
        .filter((item) => Boolean(item.command)),
    }))
    .filter((flow) => flow.steps.length > 0);

  const fallbackSteps = (Array.isArray(row.steps) ? row.steps : [])
    .filter((item): item is PlanStep => Boolean(item && typeof item === "object"))
    .map((item, idx) => ({
      id: String(item.id || "").trim() || `step_${idx + 1}`,
      title: String(item.title || "").trim() || "Plan step",
      command: normalizeCommand(String(item.command || "")),
      dependsOn: Array.isArray(item.depends_on)
        ? item.depends_on.map((dep) => String(dep || "").trim()).filter((dep) => Boolean(dep))
        : [],
      why: String(item.why || "").trim(),
      expectedEffect: String(item.expected_effect || "").trim(),
      priority: String(item.priority || "").trim().toLowerCase(),
      stepType: String(item.type || "").trim().toLowerCase(),
    }))
    .filter((item) => Boolean(item.command));

  const groupedFlows = flows.length > 0 ? flows : fallbackSteps.length > 0 ? [{ name: "Recommended Steps", flowType: "generic", steps: fallbackSteps }] : [];
  const hasAny = Boolean(goal || priority || why || expectedEffect || groupedFlows.length);
  const hasRunningFlow = Boolean(runningFlowKey);

  function stepKey(flowIdx: number, stepIdx: number, step: { id?: string; command?: string }): string {
    return String(step.id || `${flowIdx}:${stepIdx}:${String(step.command || "").trim()}`);
  }

  function flowKey(flowIdx: number, flow: { name?: string; flowType?: string }): string {
    return `${flowIdx}:${String(flow.name || "").trim()}:${String(flow.flowType || "").trim()}`;
  }

  function statusBadgeClass(status: StepRunStatus): string {
    if (status === "done") {
      return "border-emerald-500/60 bg-emerald-900/30 text-emerald-200";
    }
    if (status === "running") {
      return "border-cyan-500/60 bg-cyan-900/30 text-cyan-200";
    }
    if (status === "failed") {
      return "border-rose-500/60 bg-rose-900/30 text-rose-200";
    }
    return "border-slate-600 bg-slate-800/70 text-slate-300";
  }

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

  async function runFlow(
    flow: {
      name: string;
      flowType: string;
      steps: Array<{
        id?: string;
        title?: string;
        command?: string;
        dependsOn?: string[];
      }>;
    },
    flowIdx: number,
  ) {
    const targetProject = String(projectName || "").trim();
    const key = flowKey(flowIdx, flow);
    if (!targetProject || !flow.steps.length || hasRunningFlow) {
      return;
    }

    const stepKeys = flow.steps.map((step, idx) => stepKey(flowIdx, idx, step));
    const pendingStatus = stepKeys.reduce<Record<string, StepRunStatus>>((acc, item) => {
      acc[item] = "pending";
      return acc;
    }, {});
    setFlowStepStatusByKey((prev) => ({ ...prev, ...pendingStatus }));
    setFlowSummaryByKey((prev) => ({ ...prev, [key]: "" }));
    setFlowRunningStepByKey((prev) => ({ ...prev, [key]: "" }));
    setRunningFlowKey(key);

    let completed = 0;
    let failed = false;
    for (const [idx, step] of flow.steps.entries()) {
      const command = normalizeCommand(step.command || "");
      const currentStepKey = stepKey(flowIdx, idx, step);
      const stepTitle = String(step.title || command || `Step ${idx + 1}`).trim();
      if (!command) {
        failed = true;
        setFlowStepStatusByKey((prev) => ({ ...prev, [currentStepKey]: "failed" }));
        setFlowMessageByStepKey((prev) => ({ ...prev, [currentStepKey]: "Command is missing." }));
        break;
      }
      setFlowRunningStepByKey((prev) => ({ ...prev, [key]: stepTitle }));
      setFlowStepStatusByKey((prev) => ({ ...prev, [currentStepKey]: "running" }));
      setFlowMessageByStepKey((prev) => ({ ...prev, [currentStepKey]: "" }));
      setFlowHintByStepKey((prev) => ({ ...prev, [currentStepKey]: "" }));
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
        };
        if (!response.ok || !Boolean(payload.ok)) {
          const classified = classifyActionFailure(response, payload, {
            actionLabel: "Flow step run",
            includeLogsHint: true,
          });
          failed = true;
          setFlowStepStatusByKey((prev) => ({ ...prev, [currentStepKey]: "failed" }));
          setFlowMessageByStepKey((prev) => ({ ...prev, [currentStepKey]: classified.message }));
          setFlowHintByStepKey((prev) => ({ ...prev, [currentStepKey]: classified.hint }));
          break;
        }
        const detail = String(payload.error || payload.detail || "").trim();
        completed += 1;
        setFlowStepStatusByKey((prev) => ({ ...prev, [currentStepKey]: "done" }));
        setFlowMessageByStepKey((prev) => ({ ...prev, [currentStepKey]: detail || "Completed" }));
      } catch (error) {
        const classified = classifyNetworkFailure(error, {
          actionLabel: "Flow step run",
          includeLogsHint: true,
        });
        failed = true;
        setFlowStepStatusByKey((prev) => ({ ...prev, [currentStepKey]: "failed" }));
        setFlowMessageByStepKey((prev) => ({ ...prev, [currentStepKey]: classified.message }));
        setFlowHintByStepKey((prev) => ({ ...prev, [currentStepKey]: classified.hint }));
        break;
      }
    }

    setFlowRunningStepByKey((prev) => ({ ...prev, [key]: "" }));
    setFlowSummaryByKey((prev) => ({
      ...prev,
      [key]: failed
        ? `Stopped on failure. Completed ${completed}/${flow.steps.length}.`
        : `Flow complete (${completed}/${flow.steps.length}).`,
    }));
    setRunningFlowKey("");
    router.refresh();
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
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Flows</p>
            {groupedFlows.length === 0 ? <p className="mt-1 text-sm text-slate-300">No plan steps available.</p> : null}
            {groupedFlows.length > 0 ? (
              <div className="mt-2 space-y-3">
                {groupedFlows.slice(0, 2).map((flow, flowIdx) => (
                  <section key={`${flow.name}-${flow.flowType}-${flowIdx}`} className="rounded border border-slate-700 bg-slate-900/30 p-3">
                    {(() => {
                      const flowRunKey = flowKey(flowIdx, flow);
                      const completedCount = flow.steps.filter((step, idx) => flowStepStatusByKey[stepKey(flowIdx, idx, step)] === "done").length;
                      const totalCount = flow.steps.length;
                      const runningStep = String(flowRunningStepByKey[flowRunKey] || "").trim();
                      const flowSummary = String(flowSummaryByKey[flowRunKey] || "").trim();
                      const isThisFlowRunning = runningFlowKey === flowRunKey;
                      return (
                        <>
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <p className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                              {flow.name}
                            </p>
                            <button
                              type="button"
                              onClick={() => void runFlow(flow, flowIdx)}
                              disabled={hasRunningFlow || !String(projectName || "").trim() || totalCount === 0}
                              className="rounded-md border border-cyan-600 px-3 py-1 text-xs text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
                            >
                              {isThisFlowRunning ? "Running Flow..." : "Run Flow"}
                            </button>
                          </div>
                          <p className="text-[11px] text-slate-400">
                            Progress: {completedCount}/{totalCount}
                          </p>
                          {runningStep ? <p className="mt-1 text-[11px] text-cyan-300">Running: {runningStep}</p> : null}
                          {flowSummary ? <p className="mt-1 text-[11px] text-slate-300">{flowSummary}</p> : null}
                        </>
                      );
                    })()}
                    <div className="mt-2 space-y-2">
                      {flow.steps.slice(0, 10).map((step, idx) => {
                        const command = normalizeCommand(step.command || "");
                        const currentStepKey = stepKey(flowIdx, idx, step);
                        const runState = runStateByCommand[command] || "idle";
                        const disabled = !command || !String(projectName || "").trim() || Boolean(runningCommand);
                        const message = String(messageByCommand[command] || "").trim();
                        const hint = String(hintByCommand[command] || "").trim();
                        const flowStatus = flowStepStatusByKey[currentStepKey] || "pending";
                        const flowMessage = String(flowMessageByStepKey[currentStepKey] || "").trim();
                        const flowHint = String(flowHintByStepKey[currentStepKey] || "").trim();
                        return (
                          <article key={`${step.id || step.title}-${command}-${idx}`} className="rounded border border-slate-700 bg-slate-950/70 p-3">
                            <div className="flex items-center justify-between gap-2">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                                Step {idx + 1}
                              </p>
                              <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusBadgeClass(flowStatus)}`}>
                                {flowStatus}
                              </span>
                            </div>
                            <p className="text-sm font-semibold text-slate-100">{step.title || "Plan step"}</p>
                            <p className="mt-1 text-xs text-slate-300">{step.why || why || "No step rationale."}</p>
                            <p className="mt-1 text-[11px] text-slate-400">
                              Priority: {step.priority || "unknown"} · Type: {step.stepType || "unknown"} · Effect:{" "}
                              {step.expectedEffect || "Improves project completeness."}
                            </p>
                            {step.dependsOn.length > 0 ? (
                              <p className="mt-1 text-[11px] text-amber-300">Depends on: {step.dependsOn.join(", ")}</p>
                            ) : (
                              <p className="mt-1 text-[11px] text-slate-500">Depends on: (none)</p>
                            )}
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
                            {flowMessage ? <p className={flowStatus === "failed" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>{flowMessage}</p> : null}
                            {flowHint ? <p className="mt-1 text-xs text-cyan-300">{flowHint}</p> : null}
                            {message ? <p className={runState === "error" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>{message}</p> : null}
                            {hint ? <p className="mt-1 text-xs text-cyan-300">{hint}</p> : null}
                          </article>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
