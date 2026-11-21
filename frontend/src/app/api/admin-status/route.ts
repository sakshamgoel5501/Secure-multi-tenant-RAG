import { NextResponse } from "next/server";
import { PLATFORM_ADMIN } from "@/lib/personas";
import { mintAdminToken } from "@/lib/server/auth";
import { backendFetch } from "@/lib/server/backend";

export async function GET() {
  if (!process.env.APP_ADMIN_PASSWORD || !process.env.RAG_ADMIN_KEY) {
    return NextResponse.json({ enabled: false });
  }
  try {
    const r = await backendFetch("/admin/capabilities", {
      headers: { Authorization: `Bearer ${await mintAdminToken(PLATFORM_ADMIN)}` },
    });
    return NextResponse.json({ enabled: r.ok });
  } catch {
    return NextResponse.json({ enabled: false });
  }
}

