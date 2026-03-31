"use client";

import { useMemo, useState } from "react";
import { classifyActionFailure, classifyNetworkFailure } from "@/components/actionError";
import { UI_API_BASE } from "@/components/uiApi";

type LogSource = {
  key?: string;
  label?: string;
  path?: string;
  available?: boolean;
  content?: string;
  error?: string;
  truncated?: boolean;
  line_count?: number;
};

type LogsPayload = {
  default_source?: string;
  max_lines?: number;
  sources?: LogSource[];
};

type Props = {
  projectName?: string;
  initialLogs?: LogsPayload;
};

type FetchState = "idle" | "loading" | "error";

function normalizeLogs(payload: LogsPayload | null | undefined): { defaultSource: string; maxLines: number; sources: LogSource[] } {
  const rawSources = Array.isArray(payload?.sources) ? payload?.sources : [];
  const sources = rawSources.filter((item) => item && typeof item === "object");
  const maxLines = Number(payload?.max_lines || 200);
  const defaultSource = String(payload?.default_source || "").trim();
  return {
    defaultSource: defaultSource || (sources[0]?.key ? String(sources[0].key) : "latest"),
    maxLines: Number.isFinite(maxLines) && maxLines > 0 ? maxLines : 200,
    sources,
  };
}

function sourceLabel(source: LogSource): string {
  const key = String(source?.key || "").trim();
  const label = String(source?.label || "").trim();
  if (label) {
    return label;
  }
  if (key === "backend") {
    return "Backend";
  }
  if (key === "frontend") {
    return "Frontend";
  }
  if (key === "latest") {
    return "Latest";
  }
  return "Log";
}

export default function LogsViewerCard({ projectName, initialLogs }: Props) {
  const normalized = useMemo(() => normalizeLogs(initialLogs), [initialLogs]);
  const [logs, setLogs] = useState(normalized);
  const [selectedSource, setSelectedSource] = useState<string>(normalized.defaultSource);
  const [fetchState, setFetchState] = useState<FetchState>("idle");
  const [fetchError, setFetchError] = useState("");
  const [recoveryHint, setRecoveryHint] = useState("");

  const targetProject = String(projectName || "").trim();
  const sources = Array.isArray(logs.sources) ? logs.sources : [];
  const selected = sources.find((item) => String(item.key || "").trim() === selectedSource) || sources[0] || null;
  const selectedContent = String(selected?.content || "");
  const selectedError = String(selected?.error || "").trim();
  const selectedKey = String(selected?.key || "").trim() || "latest";
  const selectedLabel = sourceLabel(selected || {});
  const selectedAvailable = Boolean(selected?.available) && Boolean(selectedContent);
  const selectedTruncated = Boolean(selected?.truncated);

  async function refreshLogs() {
    if (!targetProject) {
      return;
    }
    setFetchError("");
    setRecoveryHint("");
    setFetchState("loading");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/logs`, {
        cache: "no-store",
      });
      const payload = (await response.json().catch(() => ({}))) as LogsPayload & { detail?: unknown; error?: unknown };
      if (!response.ok) {
        const classified = classifyActionFailure(response, payload, {
          actionLabel: "Logs refresh",
          includeLogsHint: false,
        });
        setFetchError(classified.message);
        setRecoveryHint(classified.hint);
        setFetchState("error");
        return;
      }
      const next = normalizeLogs(payload);
      setLogs(next);
      const nextSelected = next.sources.some((item) => String(item?.key || "").trim() === selectedSource)
        ? selectedSource
        : next.defaultSource;
      setSelectedSource(nextSelected);
      setFetchState("idle");
    } catch (error) {
      const classified = classifyNetworkFailure(error, {
        actionLabel: "Logs refresh",
        includeLogsHint: false,
      });
      setFetchError(classified.message);
      setRecoveryHint(classified.hint);
      setFetchState("error");
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-100">Logs</h3>
        <button
          type="button"
          onClick={() => void refreshLogs()}
          disabled={!targetProject || fetchState === "loading"}
          className="rounded-md border border-slate-600 px-2.5 py-1 text-xs text-slate-100 hover:bg-slate-800 disabled:opacity-60"
        >
          {fetchState === "loading" ? "Refreshing..." : "Refresh Logs"}
        </button>
      </div>

      {sources.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {sources.map((source) => {
            const key = String(source?.key || "").trim() || "latest";
            const selectedNow = key === selectedKey;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setSelectedSource(key)}
                disabled={fetchState === "loading"}
                className={`rounded border px-2.5 py-1 text-xs ${
                  selectedNow ? "border-cyan-500 text-cyan-200" : "border-slate-600 text-slate-300 hover:bg-slate-800"
                } disabled:opacity-60`}
              >
                {sourceLabel(source)}
              </button>
            );
          })}
        </div>
      ) : null}

      {fetchError ? <p className="mt-3 text-xs text-rose-300">Failed to load logs: {fetchError}</p> : null}
      {recoveryHint ? <p className="mt-1 text-xs text-cyan-300">{recoveryHint}</p> : null}
      {sources.length === 0 ? (
        <p className="mt-3 text-sm text-slate-300">No logs yet. Run a command or start runtime to generate logs.</p>
      ) : selectedAvailable ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-slate-400">
            Source: {selectedLabel} · Showing last {logs.maxLines} lines
            {selectedTruncated ? " (truncated)" : ""}
          </p>
          <pre className="max-h-80 overflow-auto rounded border border-slate-700 bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-200">
            {selectedContent}
          </pre>
        </div>
      ) : selectedError ? (
        <p className="mt-3 text-sm text-rose-300">{selectedError}</p>
      ) : (
        <p className="mt-3 text-sm text-slate-300">No {selectedLabel.toLowerCase()} logs yet.</p>
      )}
    </section>
  );
}
