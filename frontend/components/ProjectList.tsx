"use client";

export type ProjectListItem = {
  name: string;
  path: string;
  status: string;
  runtime: string;
  type: string;
  template: string;
  backend_url: string;
  frontend_url: string;
  is_current: boolean;
};

type Props = {
  projects: ProjectListItem[];
  selected?: string;
  onSelect?: (name: string) => void;
};

export default function ProjectList({ projects, selected, onSelect }: Props) {
  if (projects.length === 0) {
    return <div>No projects found.</div>;
  }
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Projects</h3>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {projects.map((project) => {
          const active = selected === project.name;
          return (
            <li key={project.name} style={{ marginBottom: 8 }}>
              <button
                type="button"
                onClick={() => onSelect?.(project.name)}
                style={{
                  width: "100%",
                  textAlign: "left",
                  border: active ? "1px solid #111" : "1px solid #ddd",
                  borderRadius: 6,
                  padding: "8px 10px",
                  background: active ? "#f6f6f6" : "#fff",
                  cursor: "pointer",
                }}
              >
                <div style={{ fontWeight: 600 }}>{project.name}</div>
                <div style={{ fontSize: 12, color: "#666" }}>Status: {project.status}</div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
