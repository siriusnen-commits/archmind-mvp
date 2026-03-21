"use client";

type Props = {
  project: {
    name: string;
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
      <div>Name: {project.name}</div>
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
