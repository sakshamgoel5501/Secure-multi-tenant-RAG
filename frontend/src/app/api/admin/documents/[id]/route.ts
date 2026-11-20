import { NextResponse } from "next/server";
import { TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

type Ctx = { params: Promise<{ id: string }> };
const ID = /^[\w-]{1,64}$/;

async function target(req: Request, ctx: Ctx) {
  const { id } = await ctx.params;
  const tenant = new URL(req.url).searchParams.get("tenant") ?? "";
  if (!ID.test(id) || !TENANTS.includes(tenant)) return null;
  return `/admin/documents/${id}?tenant=${encodeURIComponent(tenant)}`;
}

export async function GET(req: Request, ctx: Ctx) {
  const path = await target(req, ctx);
  if (!path) return NextResponse.json({ error: "bad document or tenant" }, { status: 400 });
  return adminProxy(path);
}

export async function DELETE(req: Request, ctx: Ctx) {
  const path = await target(req, ctx);
  if (!path) return NextResponse.json({ error: "bad document or tenant" }, { status: 400 });
  return adminProxy(path, { method: "DELETE" });
}

