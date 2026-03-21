import { NextResponse } from "next/server";

const BACKEND_UI_BASE = process.env.ARCHMIND_UI_API_BASE || "http://127.0.0.1:8010/ui";

type Params = {
  params: Promise<{ project: string }>;
};

export async function POST(request: Request, { params }: Params) {
  const resolved = await params;
  const project = decodeURIComponent(String(resolved?.project || ""));
  const bodyText = await request.text();
  try {
    const response = await fetch(`${BACKEND_UI_BASE}/projects/${encodeURIComponent(project)}/fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: bodyText,
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
