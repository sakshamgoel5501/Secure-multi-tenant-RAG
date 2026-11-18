import { NextResponse } from "next/server";
import { TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

export async function GET(req: Request) {
  const tenant = new URL(req.url).searchParams.get("tenant") ?? "";
  if (!TENANTS.includes(tenant)) return NextResponse.json({ error: "unknown tenant" }, { status: 400 });
  return adminProxy(`/admin/documents?tenant=${encodeURIComponent(tenant)}&limit=200`);
}

