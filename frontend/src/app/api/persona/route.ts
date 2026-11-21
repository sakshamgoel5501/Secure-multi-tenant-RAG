import { NextResponse } from "next/server";
import { findPersona } from "@/lib/personas";
import {
  ADMIN_COOKIE,
  currentPersona,
  PERSONA_COOKIE,
  samePassword,
  signedAdminValue,
} from "@/lib/server/auth";

const secure = () => process.env.APP_COOKIE_SECURE === "1";

export async function GET() {
  return NextResponse.json(await currentPersona());
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const persona = findPersona(body?.id);
  if (!persona) return NextResponse.json({ error: "Unknown identity." }, { status: 400 });

  if (persona.admin) {
    const expected = process.env.APP_ADMIN_PASSWORD;
    if (!expected || !process.env.RAG_ADMIN_KEY) {
      return NextResponse.json(
        { error: "Administrator identities are disabled. Set APP_ADMIN_PASSWORD and RAG_ADMIN_KEY." },
        { status: 403 },
      );
    }
    if (!samePassword(String(body?.password ?? ""), expected)) {
      return NextResponse.json({ error: "Wrong admin password." }, { status: 401 });
    }
    const res = NextResponse.json(persona);
    res.cookies.set(ADMIN_COOKIE, signedAdminValue(persona.id), {
      httpOnly: true, sameSite: "lax", path: "/", secure: secure(), maxAge: 60 * 60 * 8,
    });
    return res;
  }

  const res = NextResponse.json(persona);
  res.cookies.set(PERSONA_COOKIE, persona.id, { httpOnly: true, sameSite: "lax", path: "/" });
  res.cookies.delete(ADMIN_COOKIE);
  return res;
}

