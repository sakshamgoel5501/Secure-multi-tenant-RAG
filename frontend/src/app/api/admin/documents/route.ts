import { NextResponse } from "next/server";
import { GROUPS, TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

export async function GET(req: Request) {
  const tenant = new URL(req.url).searchParams.get("tenant") ?? "";
  if (!TENANTS.includes(tenant)) return NextResponse.json({ error: "unknown tenant" }, { status: 400 });
  return adminProxy(`/admin/documents?tenant=${encodeURIComponent(tenant)}&limit=200`);
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const title = typeof body?.title === "string" ? body.title.trim() : "";
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  const groups: unknown = body?.groups;
  if (!TENANTS.includes(body?.tenant) || !title || title.length > 200 || !text || text.length > 20000) {
    return NextResponse.json({ error: "A tenant, a title (up to 200) and text (up to 20,000) are required." }, { status: 400 });
  }
  if (!Array.isArray(groups) || !groups.every((g) => typeof g === "string" && GROUPS.includes(g))) {
    return NextResponse.json({ error: "groups must be a subset of eng, hr, fin" }, { status: 400 });
  }
  return adminProxy("/admin/documents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: body.tenant, title, text, groups }),
  });
}

