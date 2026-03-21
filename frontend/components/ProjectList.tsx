"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export type ProjectListItem = {
  name?: string;
  display_name?: string;
  path?: string;
  status?: string;
  runtime?: string;
  type?: string;
  template?: string;
  backend_url?: string;
  frontend_url?: string;
  repository?: {
    status?: string;
    url?: string;
  };
  is_current?: boolean;
};

type Props = {
  projects: ProjectListItem[];
  selectedName?: string;
};

export default function ProjectList({ projects, selectedName }: Props) {
  const router = useRouter();
  const [settingCurrentName, setSettingCurrentName] = useState("");
  const [setCurrentError, setSetCurrentError] = useState("");

  async function handleSetCurrent(projectName: string) {
    const target = String(projectName || "").trim();
    if (!target) {
      return;
    }
    setSettingCurrentName(target);
    setSetCurrentError("");
    try {
      const response = await fetch(`/api/ui/projects/${encodeURIComponent(target)}/select`, {
        method: "POST",
      });
      const payload = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
        error?: string;
      };
      if (!response.ok || !Boolean(payload.ok)) {
        const detail = String(payload.error || payload.detail || "").trim();
        setSetCurrentError(detail ? `Failed to set current project: ${detail}` : "Failed to set current project");
        return;
      }
      router.refresh();
    } catch {
      setSetCurrentError("Failed to set current project");
    } finally {
      setSettingCurrentName("");
    }
  }

  if (!projects.length) {
    return (
      <div className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">
        No projects found
      </div>
    );
  }

  return (
    <aside className="rounded-md border border-slate-700 bg-slate-900 p-3">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">Projects</h2>
      <ul className="space-y-2">
        {projects.map((project) => {
          const name = String(project.name || "");
          const displayName = String(project.display_name || name || "(unknown)");
          const isCurrent = Boolean(project.is_current);
          const isSelected = Boolean(selectedName && selectedName === name);
          const repositoryUrl = String(project.repository?.url || "").trim();
          return (
            <li key={name || displayName}>
              <div
                className={[
                  "rounded-md border px-3 py-2 transition",
                  isSelected
                    ? "border-cyan-500 bg-slate-800"
                    : "border-slate-700 bg-slate-900 hover:bg-slate-800",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <Link
                    href={name ? `/dashboard?selected=${encodeURIComponent(name)}` : "/dashboard"}
                    className="break-all text-sm font-medium text-slate-100 underline-offset-2 hover:underline"
                  >
                    {displayName}
                  </Link>
                  {isCurrent ? (
                    <span className="rounded-full border border-emerald-400 bg-emerald-900/50 px-2 py-0.5 text-[11px] font-medium text-emerald-200">
                      current
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-all text-xs text-slate-300">ID: {name || "(unknown)"}</p>
                <p className="text-xs text-slate-300">Status: {String(project.status || "unknown")}</p>
                <div className="mt-2">
                  {isCurrent ? (
                    <p className="text-xs text-emerald-300">Current project</p>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleSetCurrent(name)}
                      className="rounded-md border border-cyan-600 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-900/30"
                    >
                      Set current
                    </button>
                  )}
                </div>
                {settingCurrentName === name ? <p className="text-xs text-cyan-300">Setting current project...</p> : null}
                <div className="mt-1 text-xs text-slate-300">
                  Repository:{" "}
                  {repositoryUrl ? (
                    <a
                      href={repositoryUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-cyan-300 underline underline-offset-2 hover:text-cyan-200"
                    >
                      Open Repo
                    </a>
                  ) : (
                    <span>No repository</span>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {setCurrentError ? <p className="mt-2 break-words text-xs text-rose-300">{setCurrentError}</p> : null}
    </aside>
  );
}
