type SpecSummary = {
  stage?: string;
  entities?: number;
  apis?: number;
  pages?: number;
  history_count?: number;
};

type ProjectSummary = {
  name?: string;
  display_name?: string;
  is_current?: boolean;
  shape?: string;
  template?: string;
  spec_summary?: SpecSummary;
};

type Props = {
  project: ProjectSummary;
};

export default function ProjectSummaryCard({ project }: Props) {
  const name = String(project.name || "");
  const displayName = String(project.display_name || name || "(unknown)");
  const spec = project.spec_summary || {};

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-900">Project Summary</h3>

      <div className="mt-3 space-y-1">
        <p className="break-all text-lg font-semibold text-zinc-900">{displayName}</p>
        <p className="break-all text-xs text-zinc-500">ID: {name || "(unknown)"}</p>
        {project.is_current ? (
          <span className="inline-flex rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
            current project
          </span>
        ) : null}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-zinc-500">Shape</dt>
          <dd className="break-all text-zinc-900">{String(project.shape || "unknown")}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Template</dt>
          <dd className="break-all text-zinc-900">{String(project.template || "unknown")}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Stage</dt>
          <dd className="text-zinc-900">{String(spec.stage || "Stage 0")}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Entities</dt>
          <dd className="text-zinc-900">{Number(spec.entities || 0)}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">APIs</dt>
          <dd className="text-zinc-900">{Number(spec.apis || 0)}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">Pages</dt>
          <dd className="text-zinc-900">{Number(spec.pages || 0)}</dd>
        </div>
        <div>
          <dt className="text-zinc-500">History</dt>
          <dd className="text-zinc-900">{Number(spec.history_count || 0)}</dd>
        </div>
      </dl>
    </section>
  );
}
