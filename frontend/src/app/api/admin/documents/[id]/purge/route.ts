import { NextResponse } from "next/server";
import { TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const tenant = new URL(req.url).searchParams.get("tenant") ?? "";
  if (!/^[\w-]{1,64}$/.test(id) || !TENANTS.includes(tenant)) {
    return NextResponse.json({ error: "bad document or tenant" }, { status: 400 });
  }
  return adminProxy(`/admin/documents/${id}/purge?tenant=${encodeURIComponent(tenant)}`, {
    method: "POST",
  });
}

