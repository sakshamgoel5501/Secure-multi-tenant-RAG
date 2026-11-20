import { NextResponse } from "next/server";
import { TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => null);
  const title = typeof body?.title === "string" ? body.title.trim() : "";
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  if (!/^[\w-]{1,64}$/.test(id) || !TENANTS.includes(body?.tenant) || !title || !text || text.length > 20000) {
    return NextResponse.json({ error: "A title and new text are required." }, { status: 400 });
  }
  return adminProxy(`/admin/documents/${id}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: body.tenant, title, text }),
  });
}

