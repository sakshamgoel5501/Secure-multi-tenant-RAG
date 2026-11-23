import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { sessionToken } from "@/lib/server/session";

export async function POST(req: Request) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const body = await req.json().catch(() => null);
  const question = typeof body?.question === "string" ? body.question.trim() : "";
  if (!question || question.length > 2000) {
    return NextResponse.json({ error: "Enter a question (up to 2000 characters)." }, { status: 422 });
  }

  let r: Response;
  try {
    r = await backendFetch("/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ question, top_k: 5 }),
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable. Is `rag serve --jwt` running?" }, { status: 502 });
  }
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => null);
    const detail =
      r.status === 401
        ? "Your session has ended. Sign in again."
        : typeof data?.detail === "string"
          ? data.detail
          : `backend returned ${r.status}`;
    return NextResponse.json({ error: detail }, { status: r.status || 502 });
  }
  return new Response(r.body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}

