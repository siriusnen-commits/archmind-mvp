"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { UI_API_BASE } from "@/components/uiApi";

type Props = {
  projectName?: string;
};

type MessageType = "success" | "info" | "error";

function normalizePageInput(value: string): string {
  const trimmed = String(value || "").trim().replace(/^\/+|\/+$/g, "");
  if (!trimmed) {
    return "";
  }
  if (!trimmed.includes("/")) {
    return `${trimmed.toLowerCase()}/list`;
  }
  return trimmed.toLowerCase();
}

export default function AddPageCard({ projectName }: Props) {
  const router = useRouter();
  const [pagePath, setPagePath] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<MessageType>("success");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetProject = String(projectName || "").trim();
    const targetPagePath = normalizePageInput(pagePath);
    if (!targetProject) {
      setMessageType("error");
      setMessage("Failed to add page: project name is missing");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`${UI_API_BASE}/projects/${encodeURIComponent(targetProject)}/pages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_path: targetPagePath }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        page_path?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        const lowered = detail.toLowerCase();
        if (lowered.includes("invalid page path")) {
          setMessageType("error");
          setMessage("Failed to add page: Use format: tests/list or tests/detail");
          return;
        }
        if (lowered.includes("already exists")) {
          setMessageType("info");
          setMessage("Already exists (auto-created)");
          return;
        }
        setMessageType("error");
        setMessage(detail ? `Failed to add page: ${detail}` : "Failed to add page");
        return;
      }
      const addedPagePath = String(payload.page_path || targetPagePath).trim();
      setPagePath("");
      setMessageType("success");
      setMessage(addedPagePath ? `Page added: ${addedPagePath}` : "Page added");
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setMessageType("error");
      setMessage(`Failed to add page: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Add Page</h3>
      <form onSubmit={onSubmit} className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={pagePath}
          onChange={(event) => setPagePath(event.target.value)}
          placeholder="Page path (e.g. notes/list)"
          disabled={loading}
          className="min-w-[240px] flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-400"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {loading ? "Adding..." : "Add Page"}
        </button>
      </form>
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
