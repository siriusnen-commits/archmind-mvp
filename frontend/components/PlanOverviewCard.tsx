"use client";

import { useEffect, useState } from "react";
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

type FlowStepExecution = {
  id?: string;
  status?: "pending" | "running" | "done" | "failed" | string;
};

type FlowExecution = {
  project_id?: string;
  flow_name?: string;
  status?: "pending" | "running" | "completed" | "failed" | string;
  current_step?: string;
  steps?: FlowStepExecution[];
  updated_at?: string;
};

type Props = {
  projectName?: string;
  plan?: PlanOverview | null;
  flowExecution?: FlowExecution | null;
};

type RunState = "idle" | "running" | "success" | "error";
type StepRunStatus = "pending" | "running" | "done" | "failed";

function normalizeCommand(value: string): string {
  return String(value || "").trim();
}

function normalizeStepStatus(value: string): StepRunStatus {
  const text = String(value || "").trim().toLowerCase();
  if (text === "running") {
    return "running";
  }
  if (text === "done") {
    return "done";
  }
  if (text === "failed") {
    return "failed";
  }
  return "pending";
}

export default function PlanOverviewCard({ projectName, plan, flowExecution }: Props) {
  const router = useRouter();
  const [runningCommand, setRunningCommand] = useState("");
  const [runStateByCommand, setRunStateByCommand] = useState<Record<string, RunState>>({});
  const [messageByCommand, setMessageByCommand] = useState<Record<string, string>>({});
  const [hintByCommand, setHintByCommand] = useState<Record<string, string>>({});
  const [runningFlowName, setRunningFlowName] = useState("");
  const [resumingFlowName, setResumingFlowName] = useState("");
  const [flowMessageByName, setFlowMessageByName] = useState<Record<string, string>>({});
  const [flowHintByName, setFlowHintByName] = useState<Record<string, string>>({});

  const row = plan && typeof plan === "object" ? plan : {};
  const goal = String(row.goal || "").trim();
  const priority = String(row.priority || "").trim();
  const why = String(row.why || "").trim();
  const expectedEffect = String(row.expected_effect || "").trim();

  const execution = flowExecution && typeof flowExecution === "object" ? flowExecution : {};
  const executionFlowName = String(execution.flow_name || "").trim();
  const executionStatus = String(execution.status || "").trim().toLowerCase();
  const executionCurrentStep = String(execution.current_step || "").trim();
  const executionStepStatusById = (Array.isArray(execution.steps) ? execution.steps : []).reduce<Record<string, StepRunStatus>>((acc, item) => {
    const stepId = String(item?.id || "").trim();
    if (!stepId) {
      return acc;
    }
    acc[stepId] = normalizeStepStatus(String(item?.status || "pending"));
    return acc;
  }, {});

  const flows = (Array.isArray(row.flows) ? row.flows : [])
    .filter((flow): flow is PlanFlow => Boolean(flow && typeof flow === "object"))
    .map((flow) => ({
      name: String(flow.name || "").trim() || "Plan Flow",
      flowType: String(flow.flow_type || "").trim().toLowerCase() || "crud",
      steps: (Array.isArray(flow.steps) ? flow.steps : [])
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

  const groupedFlows =
    flows.length > 0 ? flows : fallbackSteps.length > 0 ? [{ name: "Recommended Steps", flowType: "generic", steps: fallbackSteps }] : [];
  const hasAny = Boolean(goal || priority || why || expectedEffect || groupedFlows.length);
  const hasActiveExecution = executionStatus === "running";

  useEffect(() => {
    if (!hasActiveExecution || !String(projectName || "").trim()) {
      return;
    }
    const timer = setInterval(() => {
      router.refresh();
    }, 2000);
    return () => clearInterval(timer);
  }, [hasActiveExecution, projectName, router]);

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

  async function runFlow(flowName: string) {
    const targetProject = String(projectName || "").trim();
    const normalizedFlowName = String(flowName || "").trim();
    if (!targetProject || !normalizedFlowName || hasActiveExecution || Boolean(runningFlowName)) {
      return;
    }

    setRunningFlowName(normalizedFlowName);
    setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: "" }));
    setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: "" }));

    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/run_flow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flow_name: normalizedFlowName }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: "Run Flow",
          includeLogsHint: true,
        });
        setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: classified.message }));
        setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: classified.hint }));
        return;
      }
      const detail = String(payload.detail || "").trim();
      if (detail) {
        setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: detail }));
      }
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Run Flow",
        includeLogsHint: true,
      });
      setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: classified.message }));
      setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: classified.hint }));
    } finally {
      setRunningFlowName("");
    }
  }

  async function resumeFlow(flowName: string) {
    const targetProject = String(projectName || "").trim();
    const normalizedFlowName = String(flowName || "").trim();
    if (!targetProject || !normalizedFlowName || Boolean(runningFlowName) || Boolean(resumingFlowName)) {
      return;
    }

    setResumingFlowName(normalizedFlowName);
    setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: "" }));
    setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: "" }));

    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/resume_flow`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: "Resume Flow",
          includeLogsHint: true,
        });
        setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: classified.message }));
        setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: classified.hint }));
        return;
      }
      const detail = String(payload.detail || "").trim();
      if (detail) {
        setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: detail }));
      }
      router.refresh();
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Resume Flow",
        includeLogsHint: true,
      });
      setFlowMessageByName((prev) => ({ ...prev, [normalizedFlowName]: classified.message }));
      setFlowHintByName((prev) => ({ ...prev, [normalizedFlowName]: classified.hint }));
    } finally {
      setResumingFlowName("");
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
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">Flows</p>
            {groupedFlows.length === 0 ? <p className="mt-1 text-sm text-slate-300">No plan steps available.</p> : null}
            {groupedFlows.length > 0 ? (
              <div className="mt-2 space-y-3">
                {groupedFlows.slice(0, 2).map((flow, flowIdx) => {
                  const normalizedFlowName = String(flow.name || "").trim();
                  const isActiveFlow = executionFlowName === normalizedFlowName;
                  const isRunningThisFlow = isActiveFlow && executionStatus === "running";
                  const flowMessage = String(flowMessageByName[normalizedFlowName] || "").trim();
                  const flowHint = String(flowHintByName[normalizedFlowName] || "").trim();
                  const canResume = isActiveFlow && (executionStatus === "failed" || executionStatus === "running");
                  const completedCount = flow.steps.filter((step) => {
                    if (!isActiveFlow) {
                      return false;
                    }
                    return executionStepStatusById[String(step.id || "").trim()] === "done";
                  }).length;
                  const totalCount = flow.steps.length;
                  const progress = isActiveFlow ? `${completedCount}/${totalCount}` : `0/${totalCount}`;

                  return (
                    <section key={`${flow.name}-${flow.flowType}-${flowIdx}`} className="rounded border border-slate-700 bg-slate-900/30 p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-slate-200">{flow.name}</p>
                        <div className="flex items-center gap-2">
                          {canResume ? (
                            <button
                              type="button"
                              onClick={() => void resumeFlow(normalizedFlowName)}
                              disabled={
                                !String(projectName || "").trim() ||
                                Boolean(runningFlowName) ||
                                Boolean(resumingFlowName)
                              }
                              className="rounded-md border border-amber-600 px-3 py-1 text-xs text-amber-200 hover:bg-amber-900/30 disabled:opacity-60"
                            >
                              {resumingFlowName === normalizedFlowName ? "Resuming..." : "Resume"}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => void runFlow(normalizedFlowName)}
                            disabled={
                              !String(projectName || "").trim() ||
                              totalCount === 0 ||
                              hasActiveExecution ||
                              Boolean(runningFlowName) ||
                              Boolean(resumingFlowName)
                            }
                            className="rounded-md border border-cyan-600 px-3 py-1 text-xs text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
                          >
                            {runningFlowName === normalizedFlowName || isRunningThisFlow ? "Running Flow..." : "Run Flow"}
                          </button>
                        </div>
                      </div>

                      <p className="text-[11px] text-slate-400">Progress: {progress}</p>
                      {isRunningThisFlow && executionCurrentStep ? <p className="mt-1 text-[11px] text-cyan-300">Running: {executionCurrentStep}</p> : null}
                      {isActiveFlow && executionStatus === "failed" ? (
                        <p className="mt-1 text-[11px] text-rose-300">Stopped on failure. Check step status below.</p>
                      ) : null}
                      {isActiveFlow && executionStatus === "completed" ? (
                        <p className="mt-1 text-[11px] text-emerald-300">Flow complete ({completedCount}/{totalCount}).</p>
                      ) : null}
                      {flowMessage ? <p className="mt-1 text-[11px] text-slate-300">{flowMessage}</p> : null}
                      {flowHint ? <p className="mt-1 text-[11px] text-cyan-300">{flowHint}</p> : null}

                      <div className="mt-2 space-y-2">
                        {flow.steps.slice(0, 10).map((step, idx) => {
                          const command = normalizeCommand(step.command || "");
                          const runState = runStateByCommand[command] || "idle";
                          const disabled = !command || !String(projectName || "").trim() || Boolean(runningCommand);
                          const message = String(messageByCommand[command] || "").trim();
                          const hint = String(hintByCommand[command] || "").trim();
                          const stepId = String(step.id || "").trim();
                          const backendStatus = isActiveFlow ? executionStepStatusById[stepId] || "pending" : "pending";
                          const isCurrentlyRunning = isRunningThisFlow && executionCurrentStep === stepId;
                          const flowStatus: StepRunStatus = isCurrentlyRunning ? "running" : backendStatus;

                          return (
                            <article key={`${step.id || step.title}-${command}-${idx}`} className="rounded border border-slate-700 bg-slate-950/70 p-3">
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Step {idx + 1}</p>
                                <span
                                  className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusBadgeClass(
                                    flowStatus,
                                  )}`}
                                >
                                  {flowStatus}
                                </span>
                              </div>
                              <p className="text-sm font-semibold text-slate-100">{step.title || "Plan step"}</p>
                              <p className="mt-1 text-xs text-slate-300">{step.why || why || "No step rationale."}</p>
                              <p className="mt-1 text-[11px] text-slate-400">
                                Priority: {step.priority || "unknown"} · Type: {step.stepType || "unknown"} · Effect: {" "}
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
                              {message ? <p className={runState === "error" ? "mt-2 text-xs text-rose-300" : "mt-2 text-xs text-emerald-300"}>{message}</p> : null}
                              {hint ? <p className="mt-1 text-xs text-cyan-300">{hint}</p> : null}
                            </article>
                          );
                        })}
                      </div>
                    </section>
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
