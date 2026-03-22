"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type Props = {
  projectName?: string;
};

const API_BASE = "/api/ui";

export default function AddPageCard({ projectName }: Props) {
  const router = useRouter();
  const [pagePath, setPagePath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetProject = String(projectName || "").trim();
    const targetPagePath = String(pagePath || "").trim();
    if (!targetProject) {
      setError("Failed to add page: project name is missing");
      return;
    }
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(targetProject)}/pages`, {
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
        setError(detail ? `Failed to add page: ${detail}` : "Failed to add page");
        return;
      }
      const addedPagePath = String(payload.page_path || targetPagePath).trim();
      setPagePath("");
      setSuccess(addedPagePath ? `Page added: ${addedPagePath}` : "Page added");
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Failed to add page: ${message}`);
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
      {error ? <p className="mt-2 break-words text-xs text-rose-300">{error}</p> : null}
      {!error && success ? <p className="mt-2 break-words text-xs text-emerald-300">{success}</p> : null}
    </section>
  );
}
