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

function parseNextCommand(command: string): ParsedCommand | null {
  const text = String(command || "").trim();
  if (!text) {
    return null;
  }

  if (text.startsWith("/add_field ")) {
    const rest = text.slice("/add_field ".length).trim();
    const parts = rest.split(/\s+/).filter(Boolean);
    if (parts.length < 2) {
      return null;
    }
    const entityName = String(parts[0] || "").trim();
    const fieldExpr = String(parts[1] || "").trim();
    let fieldName = "";
    let fieldType = "";
    if (fieldExpr.includes(":")) {
      const [name, type] = fieldExpr.split(":", 2);
      fieldName = String(name || "").trim();
      fieldType = String(type || "").trim();
    } else {
      fieldName = fieldExpr;
      fieldType = String(parts[2] || "").trim();
    }
    if (!entityName || !fieldName || !fieldType) {
      return null;
    }
    return {
      endpoint: "fields",
      payload: {
        entity_name: entityName,
        field_name: fieldName,
        field_type: fieldType,
      },
    };
  }

  if (text.startsWith("/add_page ")) {
    const pagePath = text.slice("/add_page ".length).trim();
    if (!pagePath) {
      return null;
    }
    return {
      endpoint: "pages",
      payload: { page_path: pagePath },
    };
  }

  if (text.startsWith("/add_api ")) {
    const rest = text.slice("/add_api ".length).trim();
    const method = rest.split(/\s+/, 1)[0]?.toUpperCase() || "";
    const path = rest.slice(method.length).trim();
    if (!method || !path) {
      return null;
    }
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
