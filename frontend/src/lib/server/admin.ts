import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";

type Init = { method?: string; body?: string; headers?: Record<string, string> };

/** Calls a backend /admin route with the key attached server-side. The browser never sees it. */
export async function adminProxy(path: string, init: Init = {}) {
  const key = process.env.RAG_ADMIN_KEY;
  if (!key) {
    return NextResponse.json({ error: "RAG_ADMIN_KEY is not set in frontend/.env.local" }, { status: 500 });
  }
  let r: Response;
  try {
    r = await backendFetch(path, { ...init, headers: { ...init.headers, "X-Admin-Key": key } });
  } catch {
    return NextResponse.json(
      { error: "Backend unreachable. Is `rag serve --jwt --admin` running?" },
      { status: 502 },
    );
  }
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `backend returned ${r.status}`;
    return NextResponse.json({ error: detail }, { status: r.status });
  }
  return NextResponse.json(body);
}


