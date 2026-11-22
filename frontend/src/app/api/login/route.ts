import { NextResponse } from "next/server";
import { ACCESS_COOKIE, accessToken } from "@/lib/access";
import { samePassword } from "@/lib/server/auth";
import { lockedFor, recordFailure, recordSuccess } from "@/lib/server/ratelimit";

export async function POST(req: Request) {
  const password = process.env.APP_ACCESS_PASSWORD;
  if (!password) return NextResponse.json({ ok: true });

  const wait = lockedFor("access-pw", req);
  if (wait > 0) {
    return NextResponse.json(
      { error: `Too many wrong passwords. Try again in ${Math.ceil(wait / 60)} min.` },
      { status: 429, headers: { "Retry-After": String(wait) } },
    );
  }
  const body = await req.json().catch(() => null);
  if (typeof body?.password !== "string" || !samePassword(body.password, password)) {
    recordFailure("access-pw", req);
    return NextResponse.json({ error: "Wrong password." }, { status: 401 });
  }
  recordSuccess("access-pw", req);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(ACCESS_COOKIE, await accessToken(password, process.env.RAG_JWT_SECRET ?? ""), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.APP_COOKIE_SECURE === "1",
    maxAge: 60 * 60 * 12,
  });
  return res;
}

