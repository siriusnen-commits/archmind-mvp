"use client";

import { useEffect, useMemo, useState } from "react";

import EvolutionCard from "../../components/EvolutionCard";
import ProjectList, { ProjectListItem } from "../../components/ProjectList";
import ProjectSummaryCard from "../../components/ProjectSummaryCard";
import ProviderCard from "../../components/ProviderCard";
import RuntimeCard from "../../components/RuntimeCard";

type ProjectDetail = {
  name: string;
  display_name: string;
  is_current: boolean;
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
  const [projectsError, setProjectsError] = useState<string>("");
  const [detailError, setDetailError] = useState<string>("");

  const selectedName = useMemo(() => {
    if (selected) {
      return selected;
    }
    const currentProject = projects.find((item) => item.is_current);
    return currentProject?.name || projects[0]?.name || "";
  }, [selected, projects]);

  const loadProjects = async (): Promise<ProjectListItem[]> => {
    setProjectsError("");
    try {
      const response = await fetch(apiBase + "/ui/projects", { cache: "no-store" });
      if (!response.ok) {
        setProjects([]);
        setProjectsError("Failed to load project data");
        return [];
      }
      const payload = (await response.json()) as { projects: ProjectListItem[] };
      const items = payload.projects || [];
      setProjects(items);
      if (items.length === 0) {
        setSelected("");
      } else if (selected.length === 0) {
        setSelected(items.find((item) => item.is_current)?.name || items[0].name);
      } else if (!items.some((item) => item.name === selected)) {
        setSelected(items.find((item) => item.is_current)?.name || items[0].name);
      }
      return items;
    } catch {
      setProjects([]);
      setProjectsError("Failed to load project data");
      return [];
    }
  };

  const loadDetail = async (projectName: string) => {
    if (projectName.length === 0) {
      setDetail(null);
      setDetailError("");
      return;
    }
    setDetailError("");
    setLoading(true);
    try {
      const response = await fetch(apiBase + "/ui/projects/" + encodeURIComponent(projectName), { cache: "no-store" });
      if (response.ok) {
        const payload = (await response.json()) as ProjectDetail;
        setDetail(payload);
      } else if (response.status === 404) {
        setDetail(null);
        setDetailError("Project not found");
      } else {
        setDetail(null);
        setDetailError("Failed to load project data");
      }
    } catch {
      setDetail(null);
      setDetailError("Failed to load project data");
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    const nextProjects = await loadProjects();
    const target = selected || nextProjects.find((item) => item.is_current)?.name || nextProjects[0]?.name || "";
    await loadDetail(target);
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

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0, 1fr)", gap: 16 }}>
        <ProjectList projects={projects} selected={selectedName} onSelect={(name) => setSelected(name)} />

        <div style={{ display: "grid", gap: 12 }}>
          {loading ? <div>Loading...</div> : null}
          {projectsError ? <div style={{ color: "#b42318" }}>{projectsError}</div> : null}
          {detail ? (
            <>
              <ProjectSummaryCard project={detail} />
              <RuntimeCard runtime={detail.runtime} />
              <ProviderCard
                projectName={detail.name}
                mode={detail.provider_mode}
                apiBaseUrl={apiBase}
                onUpdated={async (mode) => {
                  setDetail((prev) => (prev ? { ...prev, provider_mode: mode } : prev));
                  const target = selectedName || detail.name;
                  await loadProjects();
                  await loadDetail(target);
                }}
              />
              <EvolutionCard items={detail.recent_evolution} />
            </>
          ) : (
            <div style={{ color: detailError ? "#b42318" : "#555" }}>
              {detailError || (projects.length === 0 ? "No projects found" : "Select a project.")}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
