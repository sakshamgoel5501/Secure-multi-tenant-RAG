import { NextResponse } from "next/server";
import { ACCESS_COOKIE, accessToken } from "@/lib/access";

export async function POST(req: Request) {
  const password = process.env.APP_ACCESS_PASSWORD;
  if (!password) return NextResponse.json({ ok: true });
  const body = await req.json().catch(() => null);
  if (typeof body?.password !== "string" || body.password !== password) {
    return NextResponse.json({ error: "Wrong password." }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(ACCESS_COOKIE, await accessToken(password, process.env.RAG_JWT_SECRET ?? ""), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.APP_COOKIE_SECURE === "1", // set to 1 once the site is served over HTTPS
    maxAge: 60 * 60 * 12,
  });
  return res;
}

