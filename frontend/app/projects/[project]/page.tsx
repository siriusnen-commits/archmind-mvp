import Link from "next/link";
import { headers } from "next/headers";

import EvolutionCard from "@/components/EvolutionCard";
import ProjectSummaryCard from "@/components/ProjectSummaryCard";
import ProviderCard from "@/components/ProviderCard";
import RuntimeActionsCard from "@/components/RuntimeActionsCard";
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

async function resolveApiBaseUrl(): Promise<string> {
  const reqHeaders = await headers();
  const host = reqHeaders.get("x-forwarded-host") || reqHeaders.get("host") || "127.0.0.1:3000";
  const proto = reqHeaders.get("x-forwarded-proto") || "http";
  return `${proto}://${host}/api/ui`;
}

async function fetchProjectDetail(apiBaseUrl: string, name: string): Promise<{ detail: ProjectDetail | null; error: string }> {
  if (!name) {
    return { detail: null, error: "Project not found" };
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

type PageProps = {
  params: Promise<{ project: string }>;
};

export default async function ProjectDetailPage({ params }: PageProps) {
  const resolved = await params;
  const projectName = decodeURIComponent(String(resolved?.project || ""));
  const apiBaseUrl = await resolveApiBaseUrl();
  const result = await fetchProjectDetail(apiBaseUrl, projectName);
  const detail = result.detail;

  return (
    <main className="mx-auto w-full max-w-4xl p-6">
      <header className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-100">Project Detail</h1>
        <div className="flex items-center gap-2">
          <Link href="/dashboard" className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800">
            Back
          </Link>
          <Link href={`/projects/${encodeURIComponent(projectName)}`} className="rounded-md border border-slate-500 px-3 py-1.5 text-sm text-slate-100 hover:bg-slate-800">
            Refresh
          </Link>
        </div>
      </header>

      {result.error ? <p className="mb-3 rounded-md border border-rose-700 bg-rose-950/50 p-3 text-sm text-rose-200">{result.error}</p> : null}

      {detail ? (
        <section className="space-y-3">
          <ProjectSummaryCard project={detail} />
          <RuntimeCard runtime={detail.runtime} />
          <RuntimeActionsCard projectName={detail.name} />
          <ProviderCard projectName={detail.name} mode={detail.provider_mode} />
          <EvolutionCard items={Array.isArray(detail.recent_evolution) ? detail.recent_evolution : []} />
        </section>
      ) : (
        <p className="rounded-md border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">Project not found</p>
      )}
    </main>
  );
}
