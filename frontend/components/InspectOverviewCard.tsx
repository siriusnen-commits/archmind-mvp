type SpecSummary = {
  stage?: string;
  entities?: number;
  apis?: number;
  pages?: number;
  history_count?: number;
};

type RuntimeInfo = {
  overall_status?: string;
  backend_status?: string;
  frontend_status?: string;
  backend_url?: string;
  frontend_url?: string;
  backend_reason?: string;
  frontend_reason?: string;
};

type RepositoryInfo = {
  status?: string;
  url?: string;
  sync_status?: string;
  sync_reason?: string;
  sync_hint?: string;
  sync_remote_type?: string;
  last_commit_hash?: string;
  working_tree_state?: string;
};

type ProjectAnalysis = {
  entities?: string[];
  fields_by_entity?: Record<string, Array<{ name?: string; type?: string }>>;
  apis?: Array<{ method?: string; path?: string }>;
  pages?: string[];
  relation_summary?: string[];
  relation_pages?: string[];
  relation_apis?: string[];
  relation_create_flows?: string[];
  drift_warnings?: string[];
  domains?: string[];
  modules?: string[];
  next_action?: { kind?: string; message?: string; command?: string };
  next_action_explanation?: {
    gap_type?: string;
    reason_summary?: string;
    priority?: string;
    priority_reason?: string;
    expected_effect?: string;
  };
  data_consistency_notice?: string;
  data_source?: string;
};

type ProjectDetail = {
  shape?: string;
  template?: string;
  provider_mode?: string;
  spec_summary?: SpecSummary;
  runtime?: RuntimeInfo;
  repository?: RepositoryInfo;
  analysis?: ProjectAnalysis;
  architecture?: {
    app_shape?: string;
    recommended_template?: string;
    reason_summary?: string;
    backend_entry?: string;
    backend_run_mode?: string;
  };
};

type Props = {
  project?: ProjectDetail | null;
};

function toStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const rows: string[] = [];
  for (const item of value) {
    const text = String(item || "").trim();
    if (text) {
      rows.push(text);
    }
  }
  return rows;
}

function clipped(values: string[], limit: number): { rows: string[]; more: number } {
  const safe = Array.isArray(values) ? values : [];
  if (safe.length <= limit) {
    return { rows: safe, more: 0 };
  }
  return { rows: safe.slice(0, limit), more: safe.length - limit };
}

function renderPillList(values: string[], emptyText: string, limit = 10) {
  const clippedRows = clipped(values, limit);
  if (clippedRows.rows.length === 0) {
    return <p className="text-xs text-slate-400">{emptyText}</p>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {clippedRows.rows.map((row, idx) => (
        <span key={`${row}-${idx}`} className="rounded border border-slate-600 bg-slate-950/40 px-2 py-0.5 text-xs text-slate-200">
          {row}
        </span>
      ))}
      {clippedRows.more > 0 ? (
        <span className="rounded border border-slate-700 px-2 py-0.5 text-xs text-slate-400">+{clippedRows.more} more</span>
      ) : null}
    </div>
  );
}

export default function InspectOverviewCard({ project }: Props) {
  const detail = project && typeof project === "object" ? project : {};
  const spec = detail.spec_summary && typeof detail.spec_summary === "object" ? detail.spec_summary : {};
  const runtime = detail.runtime && typeof detail.runtime === "object" ? detail.runtime : {};
  const repository = detail.repository && typeof detail.repository === "object" ? detail.repository : {};
  const analysis = detail.analysis && typeof detail.analysis === "object" ? detail.analysis : {};
  const architecture = detail.architecture && typeof detail.architecture === "object" ? detail.architecture : {};

  const entities = toStringList(analysis.entities);
  const apis = Array.isArray(analysis.apis)
    ? analysis.apis
        .map((item) => `${String(item?.method || "").trim().toUpperCase()} ${String(item?.path || "").trim()}`.trim())
        .filter((item) => item && item !== "")
    : [];
  const pages = toStringList(analysis.pages);
  const domains = toStringList(analysis.domains);
  const modules = toStringList(analysis.modules);
  const relationSummary = toStringList(analysis.relation_summary);
  const relationPages = toStringList(analysis.relation_pages);
  const relationApis = toStringList(analysis.relation_apis);
  const relationCreateFlows = toStringList(analysis.relation_create_flows);
  const driftWarnings = toStringList(analysis.drift_warnings);
  const fieldsByEntity = analysis.fields_by_entity && typeof analysis.fields_by_entity === "object" ? analysis.fields_by_entity : {};
  const fieldEntities = Object.keys(fieldsByEntity).filter((key) => String(key || "").trim());
  const whyNext = analysis.next_action_explanation && typeof analysis.next_action_explanation === "object" ? analysis.next_action_explanation : {};
  const nextAction = analysis.next_action && typeof analysis.next_action === "object" ? analysis.next_action : {};
  const nextKind = String(nextAction.kind || "").trim().toLowerCase();
  const nextCommand = String(nextAction.command || "").trim();

  const hasNext = nextKind !== "none" && Boolean(nextCommand);
  const dataConsistencyNotice = String(analysis.data_consistency_notice || "").trim();

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Inspect Overview</h3>
      <p className="mt-1 text-xs text-slate-400">Full inspect-grade summary for spec, structure, relations, runtime, and sync state.</p>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {dataConsistencyNotice ? (
          <div className="md:col-span-2 rounded border border-amber-700 bg-amber-950/30 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-200">Data Fallback Notice</p>
            <p className="mt-1 text-xs text-amber-100">{dataConsistencyNotice}</p>
          </div>
        ) : null}
        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Spec Overview</h4>
          <p className="text-sm text-slate-200">Shape: {String(detail.shape || "unknown")}</p>
          <p className="text-sm text-slate-200">Template: {String(detail.template || "unknown")}</p>
          <p className="text-sm text-slate-200">Provider: {String(detail.provider_mode || "unknown")}</p>
          <p className="text-sm text-slate-200">Stage: {String(spec.stage || "Stage 0")}</p>
          <p className="text-sm text-slate-200">
            Counts: entities {Number(spec.entities || 0)} · apis {Number(spec.apis || 0)} · pages {Number(spec.pages || 0)} · history{" "}
            {Number(spec.history_count || 0)}
          </p>
        </div>

        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Architecture / Structure</h4>
          {renderPillList(domains, "No domains available")}
          {renderPillList(modules, "No modules available")}
          <p className="text-sm text-slate-200">App shape: {String(architecture.app_shape || detail.shape || "unknown")}</p>
          <p className="text-sm text-slate-200">Recommended template: {String(architecture.recommended_template || detail.template || "unknown")}</p>
          <p className="text-sm text-slate-200">Backend entrypoint: {String(architecture.backend_entry || "(not available)")}</p>
          <p className="text-sm text-slate-200">Backend run mode: {String(architecture.backend_run_mode || "(not available)")}</p>
          <p className="text-xs text-slate-400">{String(architecture.reason_summary || "No architecture reasoning summary available.")}</p>
        </div>

        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Entities & Fields</h4>
          {renderPillList(entities, "No entities available")}
          {fieldEntities.length === 0 ? (
            <p className="text-xs text-slate-400">No field map available</p>
          ) : (
            <div className="space-y-2">
              {fieldEntities.slice(0, 8).map((entity) => {
                const fields = Array.isArray(fieldsByEntity[entity]) ? fieldsByEntity[entity] : [];
                const labels = fields
                  .map((field) => `${String(field?.name || "").trim()}:${String(field?.type || "unknown").trim()}`)
                  .filter((item) => item && !item.startsWith(":"));
                return (
                  <div key={entity}>
                    <p className="text-xs font-medium text-slate-300">{entity}</p>
                    {renderPillList(labels, "No fields")}
                  </div>
                );
              })}
              {fieldEntities.length > 8 ? <p className="text-xs text-slate-400">+{fieldEntities.length - 8} more entities</p> : null}
            </div>
          )}
        </div>

        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">APIs & Pages</h4>
          <p className="text-xs text-slate-400">APIs</p>
          {renderPillList(apis, "No APIs available", 12)}
          <p className="text-xs text-slate-400">Pages</p>
          {renderPillList(pages, "No pages available", 12)}
        </div>

        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Relations & Drift</h4>
          <p className="text-xs text-slate-400">Relation Summary</p>
          {renderPillList(relationSummary, "No relations detected")}
          <p className="text-xs text-slate-400">Relation Pages</p>
          {renderPillList(relationPages, "No relation pages available")}
          <p className="text-xs text-slate-400">Relation APIs</p>
          {renderPillList(relationApis, "No relation APIs available")}
          <p className="text-xs text-slate-400">Relation Create Flow</p>
          {renderPillList(relationCreateFlows, "No relation create flow hints available")}
          <p className="text-xs text-slate-400">Drift Warnings</p>
          {driftWarnings.length === 0 ? (
            <p className="text-xs text-emerald-300">No drift warnings</p>
          ) : (
            <ul className="list-disc space-y-1 pl-4 text-xs text-amber-200">
              {driftWarnings.slice(0, 8).map((warning, idx) => (
                <li key={`${warning}-${idx}`}>{warning}</li>
              ))}
              {driftWarnings.length > 8 ? <li>+{driftWarnings.length - 8} more warnings</li> : null}
            </ul>
          )}
        </div>

        <div className="space-y-2 rounded border border-slate-700 bg-slate-950/30 p-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Runtime / Repository / Sync</h4>
          <p className="text-sm text-slate-200">Overall: {String(runtime.overall_status || "NOT_RUNNING")}</p>
          <p className="text-sm text-slate-200">Backend: {String(runtime.backend_status || "STOPPED")}</p>
          <p className="text-xs text-slate-400">{String(runtime.backend_reason || "").trim() || "No backend reason"}</p>
          <p className="text-sm text-slate-200">Frontend: {String(runtime.frontend_status || "STOPPED")}</p>
          <p className="text-xs text-slate-400">{String(runtime.frontend_reason || "").trim() || "No frontend reason"}</p>
          <p className="text-sm text-slate-200">Repository: {String(repository.status || "NONE")}</p>
          <p className="text-xs text-slate-400 break-all">{String(repository.url || "No repository URL")}</p>
          <p className="text-sm text-slate-200">Sync: {String(repository.sync_status || "NOT_ATTEMPTED")}</p>
          <p className="text-xs text-slate-400">{String(repository.sync_reason || "").trim() || "No sync reason"}</p>
          {String(repository.sync_hint || "").trim() ? <p className="text-xs text-cyan-300">{String(repository.sync_hint || "").trim()}</p> : null}
          <p className="text-xs text-slate-400">
            Remote: {String(repository.sync_remote_type || "unknown")} · Working tree: {String(repository.working_tree_state || "unknown")}
          </p>
          <p className="text-xs text-slate-400">Last commit: {String(repository.last_commit_hash || "(none)")}</p>
        </div>
      </div>

      <div className="mt-4 rounded border border-slate-700 bg-slate-950/30 p-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Why Next?</h4>
        {hasNext ? (
          <div className="space-y-1 text-sm text-slate-200">
            <p>Reason: {String(whyNext.reason_summary || "No reason summary")}</p>
            <p>
              Gap: {String(whyNext.gap_type || "unknown")} · Priority: {String(whyNext.priority || "unknown")}
            </p>
            <p className="text-xs text-slate-400">{String(whyNext.priority_reason || "No priority reason")}</p>
            <p className="text-xs text-cyan-300">{String(whyNext.expected_effect || "No expected effect")}</p>
            <p className="break-all text-xs text-cyan-200">Command: {nextCommand}</p>
          </div>
        ) : (
          <p className="text-sm text-slate-300">No immediate next rationale available.</p>
        )}
      </div>
    </section>
  );
}
