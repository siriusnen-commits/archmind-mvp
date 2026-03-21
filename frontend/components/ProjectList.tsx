import Link from "next/link";

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
  is_current?: boolean;
};

type Props = {
  projects: ProjectListItem[];
  selectedName?: string;
};

export default function ProjectList({ projects, selectedName }: Props) {
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
          return (
            <li key={name || displayName}>
              <Link
                href={name ? `/projects/${encodeURIComponent(name)}` : "/dashboard"}
                className={[
                  "block rounded-md border px-3 py-2 transition",
                  isSelected
                    ? "border-cyan-500 bg-slate-800"
                    : "border-slate-700 bg-slate-900 hover:bg-slate-800",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <span className="break-all text-sm font-medium text-slate-100">{displayName}</span>
                  {isCurrent ? (
                    <span className="rounded-full border border-emerald-400 bg-emerald-900/50 px-2 py-0.5 text-[11px] font-medium text-emerald-200">
                      current
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-all text-xs text-slate-300">ID: {name || "(unknown)"}</p>
                <p className="text-xs text-slate-300">Status: {String(project.status || "unknown")}</p>
              </Link>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
