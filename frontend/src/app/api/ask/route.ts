import { NextResponse } from "next/server";
import { backendFetch, parseServerTiming } from "@/lib/server/backend";
import { sessionToken } from "@/lib/server/session";
import type { Citation, Passage } from "@/lib/types";

export async function POST(req: Request) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const body = await req.json().catch(() => null);
  const question = typeof body?.question === "string" ? body.question.trim() : "";
  if (!question || question.length > 2000) {
    return NextResponse.json({ error: "Enter a question (up to 2000 characters)." }, { status: 422 });
  }

  const init = {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  };
  const [ask, search] = await Promise.allSettled([
    backendFetch("/ask", { ...init, body: JSON.stringify({ question, top_k: 5 }) }),
    backendFetch("/search", { ...init, body: JSON.stringify({ query: question, top_k: 5 }) }),
  ]);
  if (ask.status === "rejected") {
    return NextResponse.json({ error: "Backend unreachable. Is `rag serve --jwt` running?" }, { status: 502 });
  }

  const r = ask.value;
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const detail =
      r.status === 401
        ? "Your session has ended. Sign in again."
        : typeof data?.detail === "string"
          ? data.detail
          : `backend returned ${r.status}`;
    return NextResponse.json({ error: detail }, { status: r.status });
  }

  let passages: Passage[] = [];
  if (search.status === "fulfilled" && search.value.ok) {
    const s = await search.value.json().catch(() => null);
    const cited = new Set((data.citations as Citation[]).map((c) => c.chunk_id));
    passages = ((s?.hits ?? []) as Passage[]).filter((h) => cited.has(h.chunk_id));
  }
  return NextResponse.json({ data, passages, timing: parseServerTiming(r.headers.get("server-timing")) });
}

