import { NextResponse } from "next/server";

const BACKEND_UI_BASE = process.env.ARCHMIND_UI_API_BASE || "http://127.0.0.1:8010/ui";

type Params = {
  params: Promise<{ project: string }>;
};

export async function GET(_request: Request, { params }: Params) {
  const resolved = await params;
  const project = String(resolved?.project || "");
  try {
    const response = await fetch(`${BACKEND_UI_BASE}/projects/${encodeURIComponent(project)}`, {
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
