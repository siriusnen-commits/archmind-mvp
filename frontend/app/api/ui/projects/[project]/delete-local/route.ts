import { NextResponse } from "next/server";

import { getBackendUiBase } from "../../_backend";

type Params = {
  params: Promise<{ project: string }>;
};

export async function POST(_request: Request, { params }: Params) {
  const resolved = await params;
  const project = decodeURIComponent(String(resolved?.project || ""));
  try {
    const response = await fetch(`${getBackendUiBase()}/projects/${encodeURIComponent(project)}/delete-local`, {
      method: "POST",
      cache: "no-store",
    });
    const body = await response.text();
    return new NextResponse(body, {
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
