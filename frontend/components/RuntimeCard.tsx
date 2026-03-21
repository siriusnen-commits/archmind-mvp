"use client";

type Props = {
  runtime: {
    backend_status: string;
    frontend_status: string;
    backend_url: string;
    frontend_url: string;
  };
};

export default function RuntimeCard({ runtime }: Props) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Runtime</h3>
      <div>Backend: {runtime.backend_status}</div>
      {runtime.backend_url ? <div style={{ overflowWrap: "anywhere" }}>Backend URL: {runtime.backend_url}</div> : null}
      <div>Frontend: {runtime.frontend_status}</div>
      {runtime.frontend_url ? <div style={{ overflowWrap: "anywhere" }}>Frontend URL: {runtime.frontend_url}</div> : null}
    </div>
  );
}
