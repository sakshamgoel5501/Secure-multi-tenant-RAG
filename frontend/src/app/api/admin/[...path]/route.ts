import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { sessionToken } from "@/lib/server/session";

type Ctx = { params: Promise<{ path: string[] }> };

function explain(status: number, detail: unknown): string {
  const d = typeof detail === "string" ? detail : Array.isArray(detail) ? "Some fields are invalid." : "";
  if (status === 401) return "Your session has ended. Sign in again.";
  if (status === 403) return d || "Your role isn't allowed to do that.";
  if (status === 404 && d === "Not Found") {
    return "The backend doesn't have this feature. Start it with `rag serve --jwt --admin` and restart it after updating.";
  }
  if (status === 405) return "The backend is running an older version without this feature. Restart it.";
  return d || `The backend returned ${status}.`;
}

async function forward(req: Request, ctx: Ctx) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const { path } = await ctx.params;
  if (path.some((s) => !s || s === "." || s === "..")) {
    return NextResponse.json({ error: "Bad path." }, { status: 400 });
  }
  const target = `/admin/${path.map(encodeURIComponent).join("/")}${new URL(req.url).search}`;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let r: Response;
  try {
    r = await backendFetch(target, {
      method: req.method,
      headers: { Authorization: `Bearer ${token}`, ...(hasBody ? { "Content-Type": "application/json" } : {}) },
      body: hasBody ? await req.text() : undefined,
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable. Is `rag serve --jwt --admin` running?" }, { status: 502 });
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) return NextResponse.json({ error: explain(r.status, data?.detail) }, { status: r.status });
  return NextResponse.json(data);
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;

