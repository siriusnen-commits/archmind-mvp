"use client";

import { useEffect, useMemo, useState } from "react";

import EvolutionCard from "../../components/EvolutionCard";
import ProjectList, { ProjectListItem } from "../../components/ProjectList";
import ProjectSummaryCard from "../../components/ProjectSummaryCard";
import ProviderCard from "../../components/ProviderCard";
import RuntimeCard from "../../components/RuntimeCard";

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

export default function DashboardPage() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedName = useMemo(() => selected || (projects[0]?.name || ""), [selected, projects]);

  const loadProjects = async () => {
    const response = await fetch(apiBase + "/ui/projects", { cache: "no-store" });
    if (response.ok) {
      const payload = (await response.json()) as { projects: ProjectListItem[] };
      setProjects(payload.projects || []);
      if (selected.length === 0 && payload.projects.length > 0) {
        setSelected(payload.projects[0].name);
      }
    }
  };

  const loadDetail = async (projectName: string) => {
    if (projectName.length === 0) {
      setDetail(null);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(apiBase + "/ui/projects/" + encodeURIComponent(projectName), { cache: "no-store" });
      if (response.ok) {
        const payload = (await response.json()) as ProjectDetail;
        setDetail(payload);
      }
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    await loadProjects();
    await loadDetail(selectedName);
  };

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (selectedName.length > 0) {
      loadDetail(selectedName);
    }
  }, [selectedName]);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>ArchMind Dashboard</h1>
        <button type="button" onClick={refresh} style={{ padding: "8px 12px" }}>
          Refresh
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 16 }}>
        <ProjectList projects={projects} selected={selectedName} onSelect={(name) => setSelected(name)} />

        <div style={{ display: "grid", gap: 12 }}>
          {loading ? <div>Loading...</div> : null}
          {detail ? (
            <>
              <ProjectSummaryCard project={detail} />
              <RuntimeCard runtime={detail.runtime} />
              <ProviderCard
                projectName={detail.name}
                mode={detail.provider_mode}
                apiBaseUrl={apiBase}
                onUpdated={(mode) => setDetail({ ...detail, provider_mode: mode })}
              />
              <EvolutionCard items={detail.recent_evolution} />
            </>
          ) : (
            <div>Select a project.</div>
          )}
        </div>
      </div>
    </main>
  );
}
