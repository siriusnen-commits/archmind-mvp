"use client";

import { useEffect, useState } from "react";

import EvolutionCard from "../../../components/EvolutionCard";
import ProjectSummaryCard from "../../../components/ProjectSummaryCard";
import ProviderCard from "../../../components/ProviderCard";
import RuntimeCard from "../../../components/RuntimeCard";

type ProjectDetail = {
  name: string;
  shape: string;
  template: string;
  provider_mode: "local" | "cloud" | "auto";
  spec_summary: {
    stage: string;
    entities: number;
    apis: number;
    pages: number;
    history_count: number;
  };
  runtime: {
    backend_status: string;
    frontend_status: string;
    backend_url: string;
    frontend_url: string;
  };
  recent_evolution: string[];
};

const apiBase = process.env.NEXT_PUBLIC_ARCHMIND_API_BASE || "http://127.0.0.1:8000";

type Props = {
  params: {
    project: string;
  };
};

export default function ProjectDetailPage({ params }: Props) {
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const response = await fetch(apiBase + "/ui/projects/" + encodeURIComponent(params.project), {
        cache: "no-store",
      });
      if (response.ok) {
        const payload = (await response.json()) as ProjectDetail;
        setDetail(payload);
      } else {
        setDetail(null);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [params.project]);

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Project Detail</h1>
        <button type="button" onClick={load} style={{ padding: "8px 12px" }}>
          Refresh
        </button>
      </div>

      {loading ? <div>Loading...</div> : null}
      {detail ? (
        <div style={{ display: "grid", gap: 12 }}>
          <ProjectSummaryCard project={detail} />
          <RuntimeCard runtime={detail.runtime} />
          <ProviderCard
            projectName={detail.name}
            mode={detail.provider_mode}
            apiBaseUrl={apiBase}
            onUpdated={(mode) => setDetail({ ...detail, provider_mode: mode })}
          />
          <EvolutionCard items={detail.recent_evolution} />
        </div>
      ) : (
        <div>Project not found.</div>
      )}
    </main>
  );
}
