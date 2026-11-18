import { NextResponse } from "next/server";
import { findPersona } from "@/lib/personas";
import { currentPersona, PERSONA_COOKIE } from "@/lib/server/auth";

export async function GET() {
  return NextResponse.json(await currentPersona());
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  const persona = findPersona(body?.id);
  if (!persona) return NextResponse.json({ detail: "unknown persona" }, { status: 400 });
  const res = NextResponse.json(persona);
  res.cookies.set(PERSONA_COOKIE, persona.id, { httpOnly: true, sameSite: "lax", path: "/" });
  return res;
}


