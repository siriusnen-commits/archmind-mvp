import Link from "next/link";

import EvolutionCard from "@/components/EvolutionCard";
import AddEntityCard from "@/components/AddEntityCard";
import AddFieldCard from "@/components/AddFieldCard";
import AddApiCard from "@/components/AddApiCard";
import AddPageCard from "@/components/AddPageCard";
import DangerZoneCard from "@/components/DangerZoneCard";
import NextActionCard from "@/components/NextActionCard";
import ProjectSummaryCard from "@/components/ProjectSummaryCard";
import ProviderCard from "@/components/ProviderCard";
import RecentRunsCard from "@/components/RecentRunsCard";
import RefreshButton from "@/components/RefreshButton";
import RuntimeActionsCard from "@/components/RuntimeActionsCard";
import RuntimeCard from "@/components/RuntimeCard";
import StructureVisualizationCard from "@/components/StructureVisualizationCard";
import { resolveUiApiBaseUrl } from "@/app/_lib/uiApiBase";

type SpecSummary = {
  stage?: string;
  entities?: number;
  apis?: number;
  pages?: number;
  history_count?: number;
};

type RuntimeInfo = {
  backend_status?: string;
  frontend_status?: string;
  backend_url?: string;
  frontend_url?: string;
  backend_urls?: string[];
  frontend_urls?: string[];
};

type RepositoryInfo = {
  status?: string;
  url?: string;
};

type AnalysisNextAction = {
  kind?: string;
  message?: string;
  command?: string;
};

type ProjectAnalysis = {
  next_action?: AnalysisNextAction;
  entity_graph?: {
    nodes?: Array<{
      id?: string;
      label?: string;
      resource?: string;
      crud_complete?: boolean;
    }>;
    edges?: Array<{
      from?: string;
      to?: string;
      label?: string;
      inferred?: boolean;
    }>;
  };
  api_map?: {
    groups?: Array<{
      resource?: string;
      entity?: string;
      core_crud?: string[];
      relation_scoped?: string[];
      other?: string[];
    }>;
  };
  page_map?: {
    groups?: Array<{
      resource?: string;
      entity?: string;
      core_pages?: string[];
      relation_pages?: string[];
      other_pages?: string[];
    }>;
  };
};

type ProjectDetail = {
  name?: string;
  display_name?: string;
  is_current?: boolean;
  shape?: string;
  template?: string;
  provider_mode?: "local" | "cloud" | "auto" | string;
  spec_summary?: SpecSummary;
  entities?: string[];
  runtime?: RuntimeInfo;
  recent_evolution?: string[];
  recent_runs?: Array<{
    timestamp?: string;
    source?: string;
    command?: string;
    status?: string;
    message?: string;
    stop_reason?: string;
  }>;
  repository?: RepositoryInfo;
  analysis?: ProjectAnalysis;
};

export const dynamic = "force-dynamic";
export const revalidate = 0;

async function fetchProjectDetail(apiBaseUrl: string, name: string): Promise<{ detail: ProjectDetail | null; error: string }> {
  if (!name) {
    return { detail: null, error: "Project not found" };
  }
  try {
    const response = await fetch(`${apiBaseUrl}/projects/${encodeURIComponent(name)}`, { cache: "no-store" });
    const payload = await readJsonSafely(response);
    if (response.status === 404) {
      return { detail: null, error: "Project not found" };
    }
    if (!response.ok) {
      return { detail: null, error: extractErrorMessage(payload, "Failed to load project data") };
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return { detail: null, error: "Failed to load project data" };
    }
    return { detail: payload as ProjectDetail, error: "" };
  } catch {
    return { detail: null, error: "Failed to load project data" };
  }
}

type PageProps = {
  params: Promise<{ project: string }>;
};

export default async function ProjectDetailPage({ params }: PageProps) {
  const resolved = await params;
  const projectName = decodeURIComponent(String(resolved?.project || ""));
  const apiBaseUrl = await resolveUiApiBaseUrl();
  const result = await fetchProjectDetail(apiBaseUrl, projectName);
  const detail = result.detail;
  const analysis = detail && detail.analysis && typeof detail.analysis === "object" ? detail.analysis : {};

  return (
    <main className="mx-auto w-full max-w-4xl p-6">
      <header className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-100">Project Detail</h1>
        <div className="flex items-center gap-2">
          <Link href="/dashboard" className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800">
            Back
          </Link>
          <RefreshButton className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800" />
        </div>
      </header>

      {result.error ? <p className="mb-3 rounded-md border border-rose-700 bg-rose-950/50 p-3 text-sm text-rose-200">{result.error}</p> : null}

      {detail ? (
        <section className="space-y-3">
          <ProjectSummaryCard project={detail} />
          <NextActionCard projectName={detail.name} nextAction={analysis?.next_action} />
          <StructureVisualizationCard
            entityGraph={analysis?.entity_graph}
            apiMap={analysis?.api_map}
            pageMap={analysis?.page_map}
          />
          <RecentRunsCard items={Array.isArray(detail.recent_runs) ? detail.recent_runs : []} />
          <RuntimeCard runtime={detail.runtime} />
          <RuntimeActionsCard projectName={detail.name} />
          <AddEntityCard projectName={detail.name} />
          <AddFieldCard projectName={detail.name} entities={detail.entities} />
          <AddApiCard projectName={detail.name} />
          <AddPageCard projectName={detail.name} />
          <ProviderCard projectName={detail.name} mode={detail.provider_mode} />
          <EvolutionCard items={Array.isArray(detail.recent_evolution) ? detail.recent_evolution : []} />
          <DangerZoneCard projectName={detail.name} repositoryUrl={detail.repository?.url} />
        </section>
      ) : (
        <p className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">Project not found</p>
      )}
    </main>
  );
}

async function readJsonSafely(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function extractErrorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return fallback;
  }
  const row = payload as { detail?: unknown; error?: unknown };
  const detail = String(row.detail || "").trim();
  const error = String(row.error || "").trim();
  if (detail && error && detail !== error) {
    return `${detail}: ${error}`;
  }
  return detail || error || fallback;
}
