import { NextResponse } from "next/server";

const BACKEND_UI_BASE = process.env.ARCHMIND_UI_API_BASE || "http://127.0.0.1:8010/ui";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_UI_BASE}/projects`, { cache: "no-store" });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Failed to proxy UI API" }, { status: 502 });
  }
}
