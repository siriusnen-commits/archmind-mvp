import Link from "next/link";

import EvolutionCard from "@/components/EvolutionCard";
import ProjectSummaryCard from "@/components/ProjectSummaryCard";
import ProviderCard from "@/components/ProviderCard";
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

const API_BASE =
  process.env.NEXT_PUBLIC_ARCHMIND_UI_API_BASE ||
  "http://127.0.0.1:8010/ui";

async function fetchProjectDetail(name: string): Promise<{ detail: ProjectDetail | null; error: string }> {
  if (!name) {
    return { detail: null, error: "Project not found" };
  }
  try {
    const response = await fetch(`${API_BASE}/projects/${encodeURIComponent(name)}`, { cache: "no-store" });
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
  const projectName = String(resolved?.project || "");
  const result = await fetchProjectDetail(projectName);
  const detail = result.detail;

  return (
    <main className="mx-auto w-full max-w-4xl p-6">
      <header className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-zinc-900">Project Detail</h1>
        <div className="flex items-center gap-2">
          <Link href="/dashboard" className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50">
            Back
          </Link>
          <Link href={`/projects/${encodeURIComponent(projectName)}`} className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-50">
            Refresh
          </Link>
        </div>
      </header>

      {result.error ? <p className="mb-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{result.error}</p> : null}

      {detail ? (
        <section className="space-y-3">
          <ProjectSummaryCard project={detail} />
          <RuntimeCard runtime={detail.runtime} />
          <ProviderCard projectName={detail.name} mode={detail.provider_mode} />
          <EvolutionCard items={Array.isArray(detail.recent_evolution) ? detail.recent_evolution : []} />
        </section>
      ) : (
        <p className="rounded-md border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Project not found</p>
      )}
    </main>
  );
}
