import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";

export async function GET() {
  try {
    const r = await backendFetch("/stats");
    return NextResponse.json(await r.json(), { status: r.status });
  } catch {
    return NextResponse.json({ error: "Backend unreachable." }, { status: 502 });
  }
}

