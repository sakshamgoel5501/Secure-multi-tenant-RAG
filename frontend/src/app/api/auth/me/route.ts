import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { SESSION_COOKIE, sessionToken } from "@/lib/server/session";

export async function GET() {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  try {
    const r = await backendFetch("/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    if (r.status === 401) {
      const res = NextResponse.json({ error: "Your session has ended." }, { status: 401 });
      res.cookies.delete(SESSION_COOKIE);
      return res;
    }
    return NextResponse.json(await r.json(), { status: r.status });
  } catch {
    return NextResponse.json({ error: "Backend unreachable." }, { status: 502 });
  }
}

