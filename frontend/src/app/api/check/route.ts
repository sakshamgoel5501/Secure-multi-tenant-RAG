import { NextResponse } from "next/server";
import { findPersona } from "@/lib/personas";
import { mintToken } from "@/lib/server/auth";
import { backendFetch } from "@/lib/server/backend";

type Hit = { document_id: string; version: number; text: string };

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const persona = findPersona(body?.personaId);
  const query = typeof body?.query === "string" ? body.query.slice(0, 500) : "";
  if (!persona || persona.admin || !query) return NextResponse.json({ error: "bad request" }, { status: 400 });
  try {
    const r = await backendFetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${await mintToken(persona)}` },
      body: JSON.stringify({ query, top_k: 10 }),
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) return NextResponse.json({ error: `backend returned ${r.status}` }, { status: r.status });
    const hits = ((data?.hits ?? []) as Hit[]).map((h) => ({
      document_id: h.document_id,
      version: h.version,
      text: h.text,
    }));
    return NextResponse.json({ documentIds: hits.map((h) => h.document_id), hits });
  } catch {
    return NextResponse.json({ error: "Backend unreachable." }, { status: 502 });
  }
}

