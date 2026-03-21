type RuntimeInfo = {
  backend_status?: string;
  frontend_status?: string;
  backend_url?: string;
  frontend_url?: string;
};

type Props = {
  runtime?: RuntimeInfo;
};

export default function RuntimeCard({ runtime }: Props) {
  const data = runtime || {};
  const backendStatus = String(data.backend_status || "STOPPED");
  const frontendStatus = String(data.frontend_status || "STOPPED");
  const backendUrl = String(data.backend_url || "");
  const frontendUrl = String(data.frontend_url || "");

  return (
    <section className="rounded-md border border-zinc-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-zinc-900">Runtime</h3>
      <dl className="mt-3 space-y-2 text-sm">
        <div>
          <dt className="text-zinc-500">Backend</dt>
          <dd className="text-zinc-900">{backendStatus}</dd>
          {backendUrl ? (
            <dd className="break-all text-xs text-zinc-600">
              <a href={backendUrl} target="_blank" rel="noreferrer" className="text-blue-700 underline">
                {backendUrl}
              </a>
            </dd>
          ) : null}
        </div>
        <div>
          <dt className="text-zinc-500">Frontend</dt>
          <dd className="text-zinc-900">{frontendStatus}</dd>
          {frontendUrl ? (
            <dd className="break-all text-xs text-zinc-600">
              <a href={frontendUrl} target="_blank" rel="noreferrer" className="text-blue-700 underline">
                {frontendUrl}
              </a>
            </dd>
          ) : null}
        </div>
      </dl>
    </section>
  );
}
