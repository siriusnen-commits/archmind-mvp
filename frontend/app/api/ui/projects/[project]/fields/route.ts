import { NextResponse } from "next/server";

import { getBackendUiBase } from "../../_backend";

type Params = {
  params: Promise<{ project: string }>;
};

export async function POST(request: Request, { params }: Params) {
  const resolved = await params;
  const project = decodeURIComponent(String(resolved?.project || ""));
  const payload = (await request.json().catch(() => ({}))) as {
    entity_name?: unknown;
    field_name?: unknown;
    field_type?: unknown;
  };
  const body = {
    entity_name: String(payload.entity_name ?? ""),
    field_name: String(payload.field_name ?? ""),
    field_type: String(payload.field_type ?? ""),
  };
  try {
    const response = await fetch(`${getBackendUiBase()}/projects/${encodeURIComponent(project)}/fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const responseText = await response.text();
    return new NextResponse(responseText, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || "unknown error");
    return NextResponse.json({ detail: "Failed to proxy UI API", error: message }, { status: 502 });
  }
}
