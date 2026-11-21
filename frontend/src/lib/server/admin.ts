import { NextResponse } from "next/server";
import { currentPersona } from "@/lib/server/auth";
import { backendFetch } from "@/lib/server/backend";

type Init = { method?: string; body?: string; headers?: Record<string, string> };

function explain(status: number, detail: unknown): string {
  const d = typeof detail === "string" ? detail : "";
  if (status === 403 && d === "admin key required") {
    return "The backend rejected the admin key. RAG_ADMIN_KEY in frontend/.env.local must match the backend's.";
  }
  if (status === 404 && d === "Not Found") {
    return "The backend doesn't have this admin feature. Start it with `rag serve --jwt --admin`, and restart it after updating the code.";
  }
  if (status === 405) return "The backend is running an older version without this feature. Restart it.";
  return d || `The backend returned ${status}.`;
}

/** Calls a backend /admin route with the key attached server-side. The browser never sees it.
 *  The persona check is a demo-level guard (the cookie is client-settable); the real protection
 *  is the access password and the admin key. */
export async function adminProxy(path: string, init: Init = {}, adminOnly = true) {
  if (adminOnly && !(await currentPersona()).admin) {
    return NextResponse.json(
      { error: "Admin only. Switch to the Administrator identity first." },
      { status: 403 },
    );
  }
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
  if (!r.ok) return NextResponse.json({ error: explain(r.status, body?.detail) }, { status: r.status });
  return NextResponse.json(body);
}


