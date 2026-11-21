import { NextResponse } from "next/server";
import { PLATFORM_ADMIN, type Persona } from "@/lib/personas";
import { currentPersona, mintAdminToken } from "@/lib/server/auth";
import { backendFetch } from "@/lib/server/backend";

type Init = { method?: string; body?: string; headers?: Record<string, string> };

function explain(status: number, detail: unknown): string {
  const d = typeof detail === "string" ? detail : "";
  if (status === 401) {
    return "The backend rejected the admin token. RAG_ADMIN_KEY in frontend/.env.local must match the backend's.";
  }
  if (status === 403) return d === "outside your admin scope" ? "That is outside your admin role." : d || "Not allowed for your role.";
  if (status === 404 && d === "Not Found") {
    return "The backend doesn't have this admin feature. Start it with `rag serve --jwt --admin` and restart it after updating the code.";
  }
  if (status === 405) return "The backend is running an older version without this feature. Restart it.";
  return d || `The backend returned ${status}.`;
}

/** Calls a backend /admin route with a short-lived token for the current administrator.
 *  mode "platform" is for read-only aggregates every visitor may see (capabilities, evaluation). */
export async function adminProxy(path: string, init: Init = {}, mode: "persona" | "platform" = "persona") {
  let actor: Persona;
  if (mode === "platform") actor = PLATFORM_ADMIN;
  else {
    actor = await currentPersona();
    if (!actor.admin) {
      return NextResponse.json(
        { error: "Admin only. Choose an administrator identity first." },
        { status: 403 },
      );
    }
  }
  if (!process.env.RAG_ADMIN_KEY) {
    return NextResponse.json({ error: "RAG_ADMIN_KEY is not set in frontend/.env.local" }, { status: 500 });
  }
  let r: Response;
  try {
    r = await backendFetch(path, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${await mintAdminToken(actor)}` },
    });
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


