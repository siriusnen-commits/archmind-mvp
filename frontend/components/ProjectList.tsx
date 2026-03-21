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
      <div className="rounded-md border border-zinc-200 bg-white p-4 text-sm text-zinc-600">
        No projects found
      </div>
    );
  }

  return (
    <aside className="rounded-md border border-zinc-200 bg-white p-3">
      <h2 className="mb-3 text-sm font-semibold text-zinc-900">Projects</h2>
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
                    ? "border-zinc-900 bg-zinc-50"
                    : "border-zinc-200 bg-white hover:bg-zinc-50",
                ].join(" ")}
              >
                <div className="flex items-center gap-2">
                  <span className="break-all text-sm font-medium text-zinc-900">{displayName}</span>
                  {isCurrent ? (
                    <span className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                      current
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-all text-xs text-zinc-500">ID: {name || "(unknown)"}</p>
                <p className="text-xs text-zinc-500">Status: {String(project.status || "unknown")}</p>
              </Link>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
