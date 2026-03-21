import { headers } from "next/headers";

import EvolutionCard from "@/components/EvolutionCard";
import ProjectList, { ProjectListItem } from "@/components/ProjectList";
import ProjectSummaryCard from "@/components/ProjectSummaryCard";
import ProviderCard from "@/components/ProviderCard";
import RefreshButton from "@/components/RefreshButton";
import RuntimeCard from "@/components/RuntimeCard";

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

type ProjectDetail = {
  name?: string;
  display_name?: string;
  is_current?: boolean;
  shape?: string;
  template?: string;
  provider_mode?: "local" | "cloud" | "auto" | string;
  spec_summary?: SpecSummary;
  runtime?: RuntimeInfo;
  recent_evolution?: string[];
  repository?: RepositoryInfo;
};

export const dynamic = "force-dynamic";
export const revalidate = 0;

type DashboardPageProps = {
  searchParams: Promise<{ selected?: string | string[] }>;
};

async function resolveApiBaseUrl(): Promise<string> {
  const reqHeaders = await headers();
  const host = reqHeaders.get("x-forwarded-host") || reqHeaders.get("host") || "127.0.0.1:3000";
  const proto = reqHeaders.get("x-forwarded-proto") || "http";
  return `${proto}://${host}/api/ui`;
}

async function fetchProjects(apiBaseUrl: string): Promise<{ projects: ProjectListItem[]; error: string }> {
  try {
    const response = await fetch(`${apiBaseUrl}/projects`, { cache: "no-store" });
    if (!response.ok) {
      return { projects: [], error: "Failed to load project data" };
    }
    const payload = (await response.json()) as { projects?: ProjectListItem[] };
    return { projects: Array.isArray(payload.projects) ? payload.projects : [], error: "" };
  } catch {
    return { projects: [], error: "Failed to load project data" };
  }
}

async function fetchProjectDetail(apiBaseUrl: string, name: string): Promise<{ detail: ProjectDetail | null; error: string }> {
  if (!name) {
    return { detail: null, error: "" };
  }
  try {
    const response = await fetch(`${apiBaseUrl}/projects/${encodeURIComponent(name)}`, { cache: "no-store" });
    if (response.status === 404) {
      return { detail: null, error: "Project not found" };
    }
    if (!response.ok) {
      return { detail: null, error: "Failed to load project data" };
    }
    const payload = (await response.json()) as ProjectDetail;
    return { detail: payload, error: "" };
  } catch {
    return { detail: null, error: "Failed to load project data" };
  }
}

export default async function DashboardPage({ searchParams }: DashboardPageProps) {
  const apiBaseUrl = await resolveApiBaseUrl();
  const projectsResult = await fetchProjects(apiBaseUrl);
  const projects = projectsResult.projects;
  const resolvedSearchParams = await searchParams;
  const selectedFromQueryRaw = resolvedSearchParams?.selected;
  const selectedFromQuery = Array.isArray(selectedFromQueryRaw) ? selectedFromQueryRaw[0] : selectedFromQueryRaw;
  const selectedFromQueryName = String(selectedFromQuery || "").trim();

  const currentProject = projects.find((item) => item.is_current) || null;
  const currentProjectName = String(currentProject?.name || "");
  const hasSelectedFromQuery = projects.some((item) => String(item.name || "") === selectedFromQueryName);
  const selectedProjectName = hasSelectedFromQuery
    ? selectedFromQueryName
    : currentProjectName;

  const detailResult = await fetchProjectDetail(apiBaseUrl, selectedProjectName);
  const detail = detailResult.detail;

  return (
    <main className="mx-auto w-full max-w-6xl p-6">
      <header className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-100">ArchMind Dashboard</h1>
        <RefreshButton
          className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800"
        />
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <ProjectList projects={projects} selectedName={selectedProjectName} />

        <section className="space-y-3">
          {projectsResult.error ? <p className="rounded-md border border-rose-700 bg-rose-950/50 p-3 text-sm text-rose-200">{projectsResult.error}</p> : null}
          {!projects.length ? <p className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">No projects found</p> : null}
          {detailResult.error ? <p className="rounded-md border border-rose-700 bg-rose-950/50 p-3 text-sm text-rose-200">{detailResult.error}</p> : null}

          {detail ? (
            <>
              <ProjectSummaryCard project={detail} />
              <RuntimeCard runtime={detail.runtime} />
              <ProviderCard projectName={detail.name} mode={detail.provider_mode} />
              <EvolutionCard items={Array.isArray(detail.recent_evolution) ? detail.recent_evolution : []} />
            </>
          ) : projects.length ? (
            <p className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">No current project selected</p>
          ) : null}
        </section>
      </div>
    </main>
  );
}
