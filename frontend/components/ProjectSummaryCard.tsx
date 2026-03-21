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
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Project Summary</h3>

      <div className="mt-3 space-y-1">
        <p className="break-all text-lg font-semibold text-slate-100">{displayName}</p>
        <p className="break-all text-xs text-slate-300">ID: {name || "(unknown)"}</p>
        {project.is_current ? (
          <span className="inline-flex rounded-full border border-emerald-400 bg-emerald-900/50 px-2 py-0.5 text-[11px] font-medium text-emerald-200">
            current project
          </span>
        ) : null}
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <div>
          <dt className="text-slate-300">Shape</dt>
          <dd className="break-all text-slate-100">{String(project.shape || "unknown")}</dd>
        </div>
        <div>
          <dt className="text-slate-300">Template</dt>
          <dd className="break-all text-slate-100">{String(project.template || "unknown")}</dd>
        </div>
        <div>
          <dt className="text-slate-300">Stage</dt>
          <dd className="text-slate-100">{String(spec.stage || "Stage 0")}</dd>
        </div>
        <div>
          <dt className="text-slate-300">Entities</dt>
          <dd className="text-slate-100">{Number(spec.entities || 0)}</dd>
        </div>
        <div>
          <dt className="text-slate-300">APIs</dt>
          <dd className="text-slate-100">{Number(spec.apis || 0)}</dd>
        </div>
        <div>
          <dt className="text-slate-300">Pages</dt>
          <dd className="text-slate-100">{Number(spec.pages || 0)}</dd>
        </div>
        <div>
          <dt className="text-slate-300">History</dt>
          <dd className="text-slate-100">{Number(spec.history_count || 0)}</dd>
        </div>
      </dl>
    </section>
  );
}
