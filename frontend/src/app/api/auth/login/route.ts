import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { lockedFor, recordFailure, recordSuccess } from "@/lib/server/ratelimit";
import { cookieOptions, SESSION_COOKIE } from "@/lib/server/session";

export async function POST(req: Request) {
  const wait = lockedFor("login", req);
  if (wait > 0) {
    return NextResponse.json(
      { error: `Too many attempts. Try again in ${Math.ceil(wait / 60)} min.` },
      { status: 429, headers: { "Retry-After": String(wait) } },
    );
  }
  const body = await req.json().catch(() => null);
  const username = typeof body?.username === "string" ? body.username : "";
  const password = typeof body?.password === "string" ? body.password : "";
  if (!username || !password) return NextResponse.json({ error: "Enter a username and password." }, { status: 400 });

  let r: Response;
  try {
    r = await backendFetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable. Is `rag serve --jwt --admin` running?" }, { status: 502 });
  }
  const data = await r.json().catch(() => null);
  if (r.status === 401) {
    recordFailure("login", req);
    return NextResponse.json(
      { error: "Incorrect username or password, or the account is temporarily locked." },
      { status: 401 },
    );
  }
  if (!r.ok) {
    return NextResponse.json(
      { error: typeof data?.detail === "string" ? data.detail : `Sign-in failed (${r.status}).` },
      { status: r.status },
    );
  }
  recordSuccess("login", req);
  const res = NextResponse.json({ account: data.account });
  res.cookies.set(SESSION_COOKIE, data.token, cookieOptions(data.expires_in));
  return res;
}

