type EntityGraphNode = {
  id?: string;
  label?: string;
  resource?: string;
  crud_complete?: boolean;
};

type EntityGraphEdge = {
  from?: string;
  to?: string;
  label?: string;
  inferred?: boolean;
};

type EntityGraph = {
  nodes?: EntityGraphNode[];
  edges?: EntityGraphEdge[];
};

type ApiGroup = {
  resource?: string;
  entity?: string;
  core_crud?: string[];
  relation_scoped?: string[];
  other?: string[];
};

type ApiMap = {
  groups?: ApiGroup[];
};

type PageGroup = {
  resource?: string;
  entity?: string;
  core_pages?: string[];
  relation_pages?: string[];
  other_pages?: string[];
};

type PageMap = {
  groups?: PageGroup[];
};

type Props = {
  entityGraph?: EntityGraph;
  apiMap?: ApiMap;
  pageMap?: PageMap;
};

export default function StructureVisualizationCard({ entityGraph, apiMap, pageMap }: Props) {
  const nodes = (Array.isArray(entityGraph?.nodes) ? entityGraph.nodes : []).filter(
    (item): item is EntityGraphNode => Boolean(item && typeof item === "object"),
  );
  const edges = (Array.isArray(entityGraph?.edges) ? entityGraph.edges : []).filter(
    (item): item is EntityGraphEdge => Boolean(item && typeof item === "object"),
  );
  const apiGroups = (Array.isArray(apiMap?.groups) ? apiMap.groups : []).filter(
    (item): item is ApiGroup => Boolean(item && typeof item === "object"),
  );
  const pageGroups = (Array.isArray(pageMap?.groups) ? pageMap.groups : []).filter(
    (item): item is PageGroup => Boolean(item && typeof item === "object"),
  );
  const hasVisualization = nodes.length > 0 || edges.length > 0 || apiGroups.length > 0 || pageGroups.length > 0;

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Structure Visualization</h3>
      {!hasVisualization ? (
        <p className="mt-2 text-xs text-slate-400">Structure visualization is not available yet.</p>
      ) : null}

      <div className="mt-4 space-y-4">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Entity Graph</h4>
          {nodes.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {nodes.map((node, idx) => {
                const label = String(node?.label || node?.id || "").trim() || "(unknown)";
                const resource = String(node?.resource || "").trim();
                const crudComplete = Boolean(node?.crud_complete);
                return (
                  <article key={`${label}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">{label}</p>
                    <p className="mt-1 text-xs text-slate-300">resource: {resource || "(none)"}</p>
                    <span
                      className={
                        crudComplete
                          ? "mt-2 inline-flex rounded-full border border-emerald-400 bg-emerald-900/40 px-2 py-0.5 text-[11px] text-emerald-200"
                          : "mt-2 inline-flex rounded-full border border-amber-400 bg-amber-900/40 px-2 py-0.5 text-[11px] text-amber-200"
                      }
                    >
                      {crudComplete ? "CRUD complete" : "CRUD gap"}
                    </span>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No entities available.</p>
          )}

          {edges.length ? (
            <ul className="mt-3 space-y-1 text-xs text-slate-200">
              {edges.map((edge, idx) => {
                const from = String(edge?.from || "").trim() || "(unknown)";
                const to = String(edge?.to || "").trim() || "(unknown)";
                const label = String(edge?.label || "").trim() || "inferred";
                const inferred = Boolean(edge?.inferred) || label === "inferred";
                return (
                  <li key={`${from}-${to}-${label}-${idx}`} className="rounded border border-slate-700 bg-slate-950/60 px-2 py-1">
                    <span>{from}</span>
                    <span className="mx-2 text-slate-400">→</span>
                    <span>{to}</span>
                    <span className="ml-2 inline-flex rounded-full border border-cyan-500/60 bg-cyan-900/30 px-2 py-0.5 text-[10px] text-cyan-200">
                      {label}
                    </span>
                    {inferred ? (
                      <span className="ml-1 inline-flex rounded-full border border-violet-500/60 bg-violet-900/30 px-2 py-0.5 text-[10px] text-violet-200">
                        inferred
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No relations detected.</p>
          )}
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">API Map</h4>
          {apiGroups.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {apiGroups.map((group, idx) => {
                const resource = String(group?.resource || "").trim() || "(unknown)";
                const entity = String(group?.entity || "").trim();
                const core = Array.isArray(group?.core_crud) ? group.core_crud : [];
                const relation = Array.isArray(group?.relation_scoped) ? group.relation_scoped : [];
                const other = Array.isArray(group?.other) ? group.other : [];
                return (
                  <article key={`api-${resource}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">
                      {resource}
                      {entity ? <span className="ml-1 text-xs font-normal text-slate-400">({entity})</span> : null}
                    </p>
                    <MappedList title="Core CRUD" items={core} />
                    <MappedList title="Relation-scoped" items={relation} emptyLabel="No relation APIs" />
                    <MappedList title="Other" items={other} emptyLabel="No extra APIs" />
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No API groups available.</p>
          )}
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Page Map</h4>
          {pageGroups.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {pageGroups.map((group, idx) => {
                const resource = String(group?.resource || "").trim() || "(unknown)";
                const entity = String(group?.entity || "").trim();
                const core = Array.isArray(group?.core_pages) ? group.core_pages : [];
                const relation = Array.isArray(group?.relation_pages) ? group.relation_pages : [];
                const other = Array.isArray(group?.other_pages) ? group.other_pages : [];
                return (
                  <article key={`page-${resource}-${idx}`} className="rounded-md border border-slate-700 bg-slate-950/70 p-3">
                    <p className="text-sm font-semibold text-slate-100">
                      {resource}
                      {entity ? <span className="ml-1 text-xs font-normal text-slate-400">({entity})</span> : null}
                    </p>
                    <MappedList title="Core pages" items={core} />
                    <MappedList title="Relation pages" items={relation} emptyLabel="No relation pages" />
                    <MappedList title="Other pages" items={other} emptyLabel="No extra pages" />
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No page groups available.</p>
          )}
        </div>
      </div>
    </section>
  );
}

type MappedListProps = {
  title: string;
  items: string[];
  emptyLabel?: string;
};

function MappedList({ title, items, emptyLabel }: MappedListProps) {
  const rows = items
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
  return (
    <div className="mt-2">
      <p className="text-[11px] font-semibold text-slate-300">{title}</p>
      {rows.length ? (
        <ul className="mt-1 space-y-1 text-xs text-slate-200">
          {rows.map((item) => (
            <li key={`${title}-${item}`} className="rounded border border-slate-700 bg-slate-950/60 px-2 py-1 break-all">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[11px] text-slate-500">{emptyLabel || "None"}</p>
      )}
    </div>
  );
}
