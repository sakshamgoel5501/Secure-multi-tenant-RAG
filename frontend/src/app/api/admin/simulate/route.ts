import { NextResponse } from "next/server";
import { TENANTS } from "@/lib/personas";
import { adminProxy } from "@/lib/server/admin";

const SCENARIOS = ["out_of_order", "late_update_after_delete", "slow_update"];

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const title = typeof body?.title === "string" ? body.title.trim() : "";
  const text = typeof body?.text === "string" ? body.text.trim() : "";
  const delay = Math.min(30, Math.max(0.5, Number(body?.delay) || 5));
  if (
    !SCENARIOS.includes(body?.scenario) ||
    !TENANTS.includes(body?.tenant) ||
    !/^[\w-]{1,64}$/.test(body?.documentId ?? "") ||
    !title ||
    !text
  ) {
    return NextResponse.json({ error: "bad simulation request" }, { status: 400 });
  }
  return adminProxy("/admin/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tenant_id: body.tenant,
      document_id: body.documentId,
      scenario: body.scenario,
      title,
      text,
      delay_seconds: delay,
    }),
  });
}

