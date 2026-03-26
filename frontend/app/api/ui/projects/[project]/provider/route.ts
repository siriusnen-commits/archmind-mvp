import { NextResponse } from "next/server";

import { getBackendUiBase } from "../../_backend";

type Params = {
  params: Promise<{ project: string }>;
};

export async function GET(_request: Request, { params }: Params) {
  const resolved = await params;
  const project = decodeURIComponent(String(resolved?.project || ""));
  try {
    const response = await fetch(`${getBackendUiBase()}/projects/${encodeURIComponent(project)}/provider`, {
      cache: "no-store",
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Failed to proxy UI API" }, { status: 502 });
  }
}

export async function POST(request: Request, { params }: Params) {
  const resolved = await params;
  const project = decodeURIComponent(String(resolved?.project || ""));
  const contentType = request.headers.get("content-type") || "application/json";
  const body = await request.text();

  try {
    const response = await fetch(`${getBackendUiBase()}/projects/${encodeURIComponent(project)}/provider`, {
      method: "POST",
      headers: { "content-type": contentType },
      body,
      cache: "no-store",
    });
    const responseBody = await response.text();
    return new NextResponse(responseBody, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Failed to proxy UI API" }, { status: 502 });
  }
}
