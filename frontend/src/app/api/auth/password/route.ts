import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { cookieOptions, SESSION_COOKIE, sessionToken } from "@/lib/server/session";

export async function POST(req: Request) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  const body = await req.json().catch(() => null);
  let r: Response;
  try {
    r = await backendFetch("/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        current_password: body?.current_password ?? "",
        new_password: body?.new_password ?? "",
      }),
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable." }, { status: 502 });
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    return NextResponse.json(
      { error: typeof data?.detail === "string" ? data.detail : "Could not change the password." },
      { status: r.status },
    );
  }
  const res = NextResponse.json({ account: data.account });
  res.cookies.set(SESSION_COOKIE, data.token, cookieOptions(data.expires_in));
  return res;
}

