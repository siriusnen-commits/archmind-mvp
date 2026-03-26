import { headers } from "next/headers";

export async function resolveUiApiBaseUrl(): Promise<string> {
  const reqHeaders = await headers();
  const host = reqHeaders.get("x-forwarded-host") || reqHeaders.get("host") || "127.0.0.1:3000";
  const proto = reqHeaders.get("x-forwarded-proto") || "http";
  return `${proto}://${host}/api/ui`;
}
