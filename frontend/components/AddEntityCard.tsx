"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type Props = {
  projectName?: string;
};

const API_BASE = "/api/ui";

export default function AddEntityCard({ projectName }: Props) {
  const router = useRouter();
  const [entityName, setEntityName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetProject = String(projectName || "").trim();
    const targetEntity = String(entityName || "").trim();
    if (!targetProject) {
      setError("Failed to add entity: project name is missing");
      return;
    }
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(targetProject)}/entities`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_name: targetEntity }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        entity_name?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        setError(detail ? `Failed to add entity: ${detail}` : "Failed to add entity");
        return;
      }
      const added = String(payload.entity_name || targetEntity).trim();
      setEntityName("");
      setSuccess(added ? `Entity added: ${added}` : "Entity added");
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setError(`Failed to add entity: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Add Entity</h3>
      <form onSubmit={onSubmit} className="mt-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={entityName}
          onChange={(event) => setEntityName(event.target.value)}
          placeholder="Entity name (e.g. Task)"
          className="min-w-[220px] flex-1 rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-400"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {loading ? "Adding..." : "Add"}
        </button>
      </form>
      {error ? <p className="mt-2 break-words text-xs text-rose-300">{error}</p> : null}
      {!error && success ? <p className="mt-2 break-words text-xs text-emerald-300">{success}</p> : null}
    </section>
  );
}
