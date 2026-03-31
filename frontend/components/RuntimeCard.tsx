type RuntimeInfo = {
  overall_status?: string;
  backend_status?: string;
  frontend_status?: string;
  backend_url?: string;
  frontend_url?: string;
  backend_urls?: string[];
  frontend_urls?: string[];
};

type Props = {
  runtime?: RuntimeInfo;
};

export default function RuntimeCard({ runtime }: Props) {
  const data = runtime || {};
  const overallStatus = String(data.overall_status || "").trim() || "NOT_RUNNING";
  const backendStatus = String(data.backend_status || "STOPPED");
  const frontendStatus = String(data.frontend_status || "STOPPED");
  const backendUrl = String(data.backend_url || "").trim();
  const frontendUrl = String(data.frontend_url || "").trim();
  const backendUrls = normalizeUrls(data.backend_urls, backendUrl);
  const frontendUrls = normalizeUrls(data.frontend_urls, frontendUrl);

  return (
    <section className="rounded-md border border-slate-700 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">Runtime</h3>
      <dl className="mt-3 space-y-2 text-sm">
        <div>
          <dt className="text-slate-300">Overall</dt>
          <dd className="text-slate-100">{overallStatus}</dd>
        </div>
        <div>
          <dt className="text-slate-300">Backend</dt>
          <dd className="text-slate-100">{backendStatus}</dd>
          {backendUrls.length > 0 ? (
            <dd className="space-y-1 break-all text-xs text-slate-300">
              {backendUrls.map((url) => (
                <a
                  key={`backend-${url}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-cyan-300 underline decoration-cyan-500/70 underline-offset-2 hover:text-cyan-200"
                >
                  {url}
                </a>
              ))}
            </dd>
          ) : null}
        </div>
        <div>
          <dt className="text-slate-300">Frontend</dt>
          <dd className="text-slate-100">{frontendStatus}</dd>
          {frontendUrls.length > 0 ? (
            <dd className="space-y-1 break-all text-xs text-slate-300">
              {frontendUrls.map((url) => (
                <a
                  key={`frontend-${url}`}
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="block text-cyan-300 underline decoration-cyan-500/70 underline-offset-2 hover:text-cyan-200"
                >
                  {url}
                </a>
              ))}
            </dd>
          ) : null}
        </div>
      </dl>
    </section>
  );
}

function normalizeUrls(urls: unknown, primaryUrl: string): string[] {
  const raw = Array.isArray(urls) ? urls : [];
  const out: string[] = [];
  const seen = new Set<string>();

  if (primaryUrl) {
    seen.add(primaryUrl);
    out.push(primaryUrl);
  }

  for (const item of raw) {
    const value = String(item || "").trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    out.push(value);
  }
  return out;
}
