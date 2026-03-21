"use client";

type Props = {
  project: {
    name: string;
    display_name: string;
    is_current: boolean;
    shape: string;
    template: string;
    spec_summary: {
      stage: string;
      entities: number;
      apis: number;
      pages: number;
      history_count: number;
    };
  };
};

export default function ProjectSummaryCard({ project }: Props) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Project Summary</h3>
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 12, color: "#666" }}>Name</div>
        <div style={{ fontSize: 18, fontWeight: 700, overflowWrap: "anywhere" }}>{project.display_name || project.name}</div>
        <div style={{ fontSize: 12, color: "#666", overflowWrap: "anywhere" }}>ID: {project.name}</div>
        {project.is_current ? (
          <div style={{ marginTop: 4 }}>
            <span
              style={{
                fontSize: 11,
                lineHeight: "16px",
                border: "1px solid #0a7",
                color: "#075",
                borderRadius: 999,
                padding: "0 8px",
                background: "#edfdf8",
              }}
            >
              current project
            </span>
          </div>
        ) : null}
      </div>
      <div>Shape: {project.shape}</div>
      <div>Template: {project.template}</div>
      <hr />
      <div>Stage: {project.spec_summary.stage}</div>
      <div>Entities: {project.spec_summary.entities}</div>
      <div>APIs: {project.spec_summary.apis}</div>
      <div>Pages: {project.spec_summary.pages}</div>
      <div>History: {project.spec_summary.history_count}</div>
    </div>
  );
}
