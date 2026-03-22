"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type Props = {
  projectName?: string;
};

const API_BASE = "/api/ui";
const METHODS = ["GET", "POST", "PUT", "DELETE"];
type MessageType = "success" | "info" | "error";

export default function AddApiCard({ projectName }: Props) {
  const router = useRouter();
  const [method, setMethod] = useState("GET");
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<MessageType>("success");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetProject = String(projectName || "").trim();
    const targetMethod = String(method || "").trim();
    const targetPath = String(path || "").trim();
    if (!targetProject) {
      setMessageType("error");
      setMessage("Failed to add API: project name is missing");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(targetProject)}/apis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ method: targetMethod, path: targetPath }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
        method?: string;
        path?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        const addedMethod = String(payload.method || targetMethod).trim();
        const addedPath = String(payload.path || targetPath).trim();
        if (detail.toLowerCase().includes("already exists")) {
          setMessageType("info");
          setMessage(
            addedMethod && addedPath
              ? `Already exists (auto-created): ${addedMethod} ${addedPath}`
              : "Already exists (auto-created)"
          );
          return;
        }
        setMessageType("error");
        setMessage(detail ? `Failed to add API: ${detail}` : "Failed to add API");
        return;
      }
      const addedMethod = String(payload.method || targetMethod).trim();
      const addedPath = String(payload.path || targetPath).trim();
      setPath("");
      setMessageType("success");
      setMessage(addedMethod && addedPath ? `API added: ${addedMethod} ${addedPath}` : "API added");
      router.refresh();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e || "unknown error");
      setMessageType("error");
      setMessage(`Failed to add API: ${message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Add API</h3>
      <form onSubmit={onSubmit} className="mt-3 grid gap-2 sm:grid-cols-4">
        <select
          value={method}
          onChange={(event) => setMethod(event.target.value)}
          disabled={loading}
          className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100"
        >
          {METHODS.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="Path (e.g. /tasks)"
          disabled={loading}
          className="sm:col-span-2 rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-400"
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded-md border border-cyan-600 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-900/30 disabled:opacity-60"
        >
          {loading ? "Adding..." : "Add API"}
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
