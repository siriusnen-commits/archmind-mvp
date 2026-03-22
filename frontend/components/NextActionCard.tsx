"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

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

const API_BASE = "/api/ui";

type ParsedCommand =
  | { endpoint: "fields"; payload: { entity_name: string; field_name: string; field_type: string } }
  | { endpoint: "pages"; payload: { page_path: string } }
  | { endpoint: "apis"; payload: { method: string; path: string } };

function normalizeCommandText(value: string): string {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const singleLine = raw.split(/\r?\n/, 1)[0] || "";
  const withoutLabel = singleLine.replace(/^command:\s*/i, "").trim();
  return withoutLabel.replace(/^`|`$/g, "").trim();
}

function parseNextCommand(command: string): ParsedCommand | null {
  const text = normalizeCommandText(command);
  if (!text) {
    return null;
  }

  const addFieldMatch = text.match(/^\/add_field\s+([A-Za-z][A-Za-z0-9_]*)\s+([A-Za-z][A-Za-z0-9_]*)\s*:\s*([A-Za-z][A-Za-z0-9_]*)\s*$/);
  if (addFieldMatch) {
    const entityName = String(addFieldMatch[1] || "").trim();
    const fieldName = String(addFieldMatch[2] || "").trim();
    const fieldType = String(addFieldMatch[3] || "").trim().toLowerCase();
    return {
      endpoint: "fields",
      payload: {
        entity_name: entityName,
        field_name: fieldName,
        field_type: fieldType,
      },
    };
  }

  const addPageMatch = text.match(/^\/add_page\s+([A-Za-z0-9_/-]+)\s*$/);
  if (addPageMatch) {
    const pagePath = String(addPageMatch[1] || "").trim();
    return {
      endpoint: "pages",
      payload: { page_path: pagePath },
    };
  }

  const addApiMatch = text.match(/^\/add_api\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)\s*$/i);
  if (addApiMatch) {
    const method = String(addApiMatch[1] || "").toUpperCase();
    const path = String(addApiMatch[2] || "").trim();
    return {
      endpoint: "apis",
      payload: { method, path },
    };
  }

  return null;
}

function isNoImmediate(nextAction: NextAction): boolean {
  const kind = String(nextAction.kind || "").trim().toLowerCase();
  const message = String(nextAction.message || "").trim().toLowerCase();
  return kind === "none" || !message || message === "no immediate suggestions.";
}

export default function NextActionCard({ projectName, nextAction }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<MessageType>("success");

  const action = nextAction || {};
  const noImmediate = isNoImmediate(action);
  const actionMessage = noImmediate ? "No immediate next action." : String(action.message || "").trim();
  const command = String(action.command || "").trim();
  const canRun = Boolean(command && !noImmediate && String(projectName || "").trim());

  async function runNextAction() {
    const targetProject = String(projectName || "").trim();
    if (!targetProject) {
      setMessageType("error");
      setMessage("Failed to run next action: project name is missing");
      return;
    }
    const parsed = parseNextCommand(command);
    if (!parsed) {
      setMessageType("error");
      setMessage("Failed to run next action: unsupported or invalid command");
      return;
    }

    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(targetProject)}/${parsed.endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.payload),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        entity_name?: string;
        field_name?: string;
        field_type?: string;
      };
      const detail = String(payload.error || payload.detail || "").trim();

      if (!response.ok || !Boolean(payload.ok)) {
        if (detail.toLowerCase().includes("already exists")) {
          setMessageType("info");
          setMessage("Already exists (auto-created)");
          return;
        }
        setMessageType("error");
        setMessage(detail ? `Failed to run next action: ${detail}` : "Failed to run next action");
        return;
      }

      if (parsed.endpoint === "fields") {
        const actualEntity = String(payload.entity_name || "").trim();
        const actualField = String(payload.field_name || "").trim();
        const actualType = String(payload.field_type || "").trim().toLowerCase();
        const expectedEntity = parsed.payload.entity_name;
        const expectedField = parsed.payload.field_name;
        const expectedType = parsed.payload.field_type.toLowerCase();
        if (actualEntity && (actualEntity !== expectedEntity || actualField !== expectedField || actualType !== expectedType)) {
          setMessageType("error");
          setMessage(
            `Failed to run next action: target mismatch (expected ${expectedEntity}.${expectedField}:${expectedType}, got ${actualEntity}.${actualField}:${actualType})`
          );
          return;
        }
      }

      setMessageType("success");
      setMessage(detail || "Next action executed");
      router.refresh();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || "unknown error");
      setMessageType("error");
      setMessage(`Failed to run next action: ${detail}`);
    } finally {
      setLoading(false);
    }
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
          disabled={!canRun || loading}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {loading ? "Running..." : "Run"}
        </button>
      </div>
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
