import { NextResponse } from "next/server";

import { getBackendUiBase } from "../_backend";

export async function POST(request: Request) {
  const bodyText = await request.text();
  try {
    const response = await fetch(`${getBackendUiBase()}/projects/idea_local`, {
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
