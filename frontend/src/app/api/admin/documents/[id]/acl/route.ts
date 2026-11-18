import { NextResponse } from "next/server";
import { GROUPS, TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

export async function PUT(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => null);
  const groups: unknown = body?.groups;
  if (!/^[\w-]+$/.test(id) || !TENANTS.includes(body?.tenant)) {
    return NextResponse.json({ error: "bad document or tenant" }, { status: 400 });
  }
  if (!Array.isArray(groups) || !groups.every((g) => typeof g === "string" && GROUPS.includes(g))) {
    return NextResponse.json({ error: "groups must be a subset of eng, hr, fin" }, { status: 400 });
  }
  return adminProxy(`/admin/documents/${id}/acl`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: body.tenant, groups }),
  });
}

