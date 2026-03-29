"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type EntityGraphNode = {
  id?: string;
  label?: string;
  resource?: string;
  crud_complete?: boolean;
};

type EntityGraphEdge = {
  from?: string;
  to?: string;
  label?: string;
  inferred?: boolean;
};

type EntityGraph = {
  nodes?: EntityGraphNode[];
  edges?: EntityGraphEdge[];
};

type ApiGroup = {
  resource?: string;
  entity?: string;
  core_crud?: string[];
  relation_scoped?: string[];
  other?: string[];
};

type ApiMap = {
  groups?: ApiGroup[];
};

type PageGroup = {
  resource?: string;
  entity?: string;
  core_pages?: string[];
  relation_pages?: string[];
  other_pages?: string[];
};

type PageMap = {
  groups?: PageGroup[];
};

type Props = {
  projectName?: string;
  entityGraph?: EntityGraph;
  apiMap?: ApiMap;
  pageMap?: PageMap;
  visualizationGaps?: VisualizationGap[];
};

type VisualizationGap = {
  gap_type?: string;
  resource?: string;
  expected?: string;
  command?: string;
  priority?: string;
  actionable?: string;
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

function buildCommandKey(command: string): string {
  return normalizeCommandText(command).toLowerCase();
}

export default function StructureVisualizationCard({ projectName, entityGraph, apiMap, pageMap, visualizationGaps }: Props) {
  const router = useRouter();
  const [runningCommand, setRunningCommand] = useState("");
  const [executedCommand, setExecutedCommand] = useState("");
  const [messagesByCommand, setMessagesByCommand] = useState<Record<string, string>>({});
  const [messageTypeByCommand, setMessageTypeByCommand] = useState<Record<string, MessageType>>({});
  const [runStateByCommand, setRunStateByCommand] = useState<Record<string, RunState>>({});

  const nodes = (Array.isArray(entityGraph?.nodes) ? entityGraph.nodes : []).filter(
    (item): item is EntityGraphNode => Boolean(item && typeof item === "object"),
  );
  const edges = (Array.isArray(entityGraph?.edges) ? entityGraph.edges : []).filter(
    (item): item is EntityGraphEdge => Boolean(item && typeof item === "object"),
  );
  const apiGroups = (Array.isArray(apiMap?.groups) ? apiMap.groups : []).filter(
    (item): item is ApiGroup => Boolean(item && typeof item === "object"),
  );
  const pageGroups = (Array.isArray(pageMap?.groups) ? pageMap.groups : []).filter(
    (item): item is PageGroup => Boolean(item && typeof item === "object"),
  );
  const gaps = (Array.isArray(visualizationGaps) ? visualizationGaps : []).filter(
    (item): item is VisualizationGap => Boolean(item && typeof item === "object"),
  );

  const apiGapsByResource = new Map<string, VisualizationGap[]>();
  const pageGapsByResource = new Map<string, VisualizationGap[]>();
  for (const gap of gaps) {
    const gapType = String(gap.gap_type || "").trim().toLowerCase();
    const resource = String(gap.resource || "").trim().toLowerCase();
    if (!resource || String(gap.actionable || "").trim().toLowerCase() !== "true") {
      continue;
    }
    if (gapType === "missing_relation_scoped_api") {
      const rows = apiGapsByResource.get(resource) || [];
      rows.push(gap);
      apiGapsByResource.set(resource, rows);
    } else if (gapType === "missing_relation_page" || gapType === "relation_page_placeholder") {
      const rows = pageGapsByResource.get(resource) || [];
      rows.push(gap);
      pageGapsByResource.set(resource, rows);
    }
  }

  const hasVisualization = nodes.length > 0 || edges.length > 0 || apiGroups.length > 0 || pageGroups.length > 0;

  async function runFixCommand(rawCommand: string) {
    const targetProject = String(projectName || "").trim();
    const normalizedCommand = normalizeCommandText(rawCommand);
    const commandKey = buildCommandKey(normalizedCommand);
    if (!targetProject || !normalizedCommand || !commandKey) {
      return;
    }
    setRunningCommand(commandKey);
    setExecutedCommand(normalizedCommand);
    setRunStateByCommand((prev) => ({ ...prev, [commandKey]: "running" }));
    setMessagesByCommand((prev) => ({ ...prev, [commandKey]: "" }));
    setMessageTypeByCommand((prev) => ({ ...prev, [commandKey]: "success" }));
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
        setRunStateByCommand((prev) => ({ ...prev, [commandKey]: "error" }));
        setMessageTypeByCommand((prev) => ({ ...prev, [commandKey]: "error" }));
        setMessagesByCommand((prev) => ({ ...prev, [commandKey]: detail ? `Failed: ${detail}` : "Failed to run fix action" }));
        return;
      }
      setRunStateByCommand((prev) => ({ ...prev, [commandKey]: "success" }));
      setMessageTypeByCommand((prev) => ({ ...prev, [commandKey]: "success" }));
      setMessagesByCommand((prev) => ({ ...prev, [commandKey]: detail || "Completed" }));
      router.refresh();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || "unknown error");
      setRunStateByCommand((prev) => ({ ...prev, [commandKey]: "error" }));
      setMessageTypeByCommand((prev) => ({ ...prev, [commandKey]: "error" }));
      setMessagesByCommand((prev) => ({ ...prev, [commandKey]: `Failed: ${detail}` }));
    } finally {
      setRunningCommand("");
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Structure Visualization</h3>
      {!hasVisualization ? (
        <p className="mt-2 text-xs text-slate-400">Structure visualization is not available yet.</p>
      ) : null}

      <div className="mt-4 space-y-4">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Entity Graph</h4>
          {nodes.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {nodes.map((node, idx) => {
                const label = String(node?.label || node?.id || "").trim() || "(unknown)";
                const resource = String(node?.resource || "").trim();
                const crudComplete = Boolean(node?.crud_complete);
                return (
                  <article key={`${label}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">{label}</p>
                    <p className="mt-1 text-xs text-slate-300">resource: {resource || "(none)"}</p>
                    <span
                      className={
                        crudComplete
                          ? "mt-2 inline-flex rounded-full border border-emerald-400 bg-emerald-900/40 px-2 py-0.5 text-[11px] text-emerald-200"
                          : "mt-2 inline-flex rounded-full border border-amber-400 bg-amber-900/40 px-2 py-0.5 text-[11px] text-amber-200"
                      }
                    >
                      {crudComplete ? "CRUD complete" : "CRUD gap"}
                    </span>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No entities available.</p>
          )}

          {edges.length ? (
            <ul className="mt-3 space-y-1 text-xs text-slate-200">
              {edges.map((edge, idx) => {
                const from = String(edge?.from || "").trim() || "(unknown)";
                const to = String(edge?.to || "").trim() || "(unknown)";
                const label = String(edge?.label || "").trim() || "inferred";
                const inferred = Boolean(edge?.inferred) || label === "inferred";
                return (
                  <li key={`${from}-${to}-${label}-${idx}`} className="rounded border border-slate-700 bg-slate-950/60 px-2 py-1">
                    <span>{from}</span>
                    <span className="mx-2 text-slate-400">→</span>
                    <span>{to}</span>
                    <span className="ml-2 inline-flex rounded-full border border-cyan-500/60 bg-cyan-900/30 px-2 py-0.5 text-[10px] text-cyan-200">
                      {label}
                    </span>
                    {inferred ? (
                      <span className="ml-1 inline-flex rounded-full border border-violet-500/60 bg-violet-900/30 px-2 py-0.5 text-[10px] text-violet-200">
                        inferred
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No relations detected.</p>
          )}
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">API Map</h4>
          {apiGroups.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {apiGroups.map((group, idx) => {
                const resource = String(group?.resource || "").trim() || "(unknown)";
                const entity = String(group?.entity || "").trim();
                const core = Array.isArray(group?.core_crud) ? group.core_crud : [];
                const relation = Array.isArray(group?.relation_scoped) ? group.relation_scoped : [];
                const other = Array.isArray(group?.other) ? group.other : [];
                const relationGaps = apiGapsByResource.get(resource.toLowerCase()) || [];
                return (
                  <article key={`api-${resource}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">
                      {resource}
                      {entity ? <span className="ml-1 text-xs font-normal text-slate-400">({entity})</span> : null}
                    </p>
                    <MappedList title="Core CRUD" items={core} />
                    <MappedList title="Relation-scoped" items={relation} emptyLabel="No relation APIs" />
                    <GapActionList
                      title="Relation-scoped Gaps"
                      gaps={relationGaps}
                      runningCommand={runningCommand}
                      runStateByCommand={runStateByCommand}
                      messagesByCommand={messagesByCommand}
                      messageTypeByCommand={messageTypeByCommand}
                      onRun={runFixCommand}
                      canRun={Boolean(String(projectName || "").trim())}
                    />
                    <MappedList title="Other" items={other} emptyLabel="No extra APIs" />
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No API groups available.</p>
          )}
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Page Map</h4>
          {pageGroups.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {pageGroups.map((group, idx) => {
                const resource = String(group?.resource || "").trim() || "(unknown)";
                const entity = String(group?.entity || "").trim();
                const core = Array.isArray(group?.core_pages) ? group.core_pages : [];
                const relation = Array.isArray(group?.relation_pages) ? group.relation_pages : [];
                const other = Array.isArray(group?.other_pages) ? group.other_pages : [];
                const relationGaps = pageGapsByResource.get(resource.toLowerCase()) || [];
                return (
                  <article key={`page-${resource}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">
                      {resource}
                      {entity ? <span className="ml-1 text-xs font-normal text-slate-400">({entity})</span> : null}
                    </p>
                    <MappedList title="Core pages" items={core} />
                    <MappedList title="Relation pages" items={relation} emptyLabel="No relation pages" />
                    <GapActionList
                      title="Relation Page Gaps"
                      gaps={relationGaps}
                      runningCommand={runningCommand}
                      runStateByCommand={runStateByCommand}
                      messagesByCommand={messagesByCommand}
                      messageTypeByCommand={messageTypeByCommand}
                      onRun={runFixCommand}
                      canRun={Boolean(String(projectName || "").trim())}
                    />
                    <MappedList title="Other pages" items={other} emptyLabel="No extra pages" />
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No page groups available.</p>
          )}
        </div>
      </div>
      {executedCommand ? <p className="mt-3 break-words text-xs text-slate-300">Executed: {executedCommand}</p> : null}
    </section>
  );
}

type MappedListProps = {
  title: string;
  items: string[];
  emptyLabel?: string;
};

function MappedList({ title, items, emptyLabel }: MappedListProps) {
  const rows = items
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
  return (
    <div className="mt-2">
      <p className="text-[11px] font-semibold text-slate-300">{title}</p>
      {rows.length ? (
        <ul className="mt-1 space-y-1 text-xs text-slate-200">
          {rows.map((item) => (
            <li key={`${title}-${item}`} className="rounded border border-slate-700 bg-slate-950/60 px-2 py-1 break-all">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[11px] text-slate-500">{emptyLabel || "None"}</p>
      )}
    </div>
  );
}

type GapActionListProps = {
  title: string;
  gaps: VisualizationGap[];
  runningCommand: string;
  runStateByCommand: Record<string, RunState>;
  messagesByCommand: Record<string, string>;
  messageTypeByCommand: Record<string, MessageType>;
  onRun: (command: string) => Promise<void>;
  canRun: boolean;
};

function GapActionList({
  title,
  gaps,
  runningCommand,
  runStateByCommand,
  messagesByCommand,
  messageTypeByCommand,
  onRun,
  canRun,
}: GapActionListProps) {
  const rows = gaps.filter((item) => {
    const command = normalizeCommandText(String(item.command || ""));
    const expected = String(item.expected || "").trim();
    return Boolean(command && expected);
  });
  if (!rows.length) {
    return <></>;
  }
  return (
    <div className="mt-2">
      <p className="text-[11px] font-semibold text-amber-300">{title}</p>
      <ul className="mt-1 space-y-2 text-xs text-slate-200">
        {rows.map((gap, idx) => {
          const expected = String(gap.expected || "").trim();
          const command = normalizeCommandText(String(gap.command || ""));
          const commandKey = buildCommandKey(command);
          const runState = runStateByCommand[commandKey] || "idle";
          const isRunning = runningCommand === commandKey;
          const disabled = !canRun || Boolean(runningCommand) || !command;
          const message = String(messagesByCommand[commandKey] || "").trim();
          const messageType = messageTypeByCommand[commandKey] || "info";
          return (
            <li key={`${title}-${expected}-${idx}`} className="rounded border border-amber-700/60 bg-amber-950/20 px-2 py-2">
              <p className="break-all text-[11px] text-amber-200">Missing: {expected}</p>
              <button
                type="button"
                onClick={() => onRun(command)}
                disabled={disabled}
                className="mt-2 rounded-md border border-amber-500 px-2 py-1 text-[11px] text-amber-200 hover:bg-amber-900/30 disabled:opacity-60"
              >
                {isRunning || runState === "running" ? "Fixing..." : runState === "success" ? "Fixed" : "Fix"}
              </button>
              {message ? (
                <p
                  className={
                    messageType === "error"
                      ? "mt-1 break-words text-[11px] text-rose-300"
                      : messageType === "success"
                        ? "mt-1 break-words text-[11px] text-emerald-300"
                        : "mt-1 break-words text-[11px] text-cyan-300"
                  }
                >
                  {message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
