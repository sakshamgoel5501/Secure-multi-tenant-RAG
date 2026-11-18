import { SignJWT } from "jose";
import { cookies } from "next/headers";
import { DEFAULT_PERSONA_ID, findPersona, type Persona } from "@/lib/personas";

export const PERSONA_COOKIE = "rag_persona";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is not set (see frontend/.env.local)`);
  return v;
}

export async function currentPersona(): Promise<Persona> {
  const store = await cookies();
  return (
    findPersona(store.get(PERSONA_COOKIE)?.value) ?? (findPersona(DEFAULT_PERSONA_ID) as Persona)
  );
}

/** Short-lived token for the selected demo persona. The secret never leaves the server. */
export async function mintToken(p: Persona): Promise<string> {
  const secret = new TextEncoder().encode(env("RAG_JWT_SECRET"));
  return new SignJWT({ tenant: p.tenant, groups: [p.group] })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(`demo-${p.id}`)
    .setAudience("rag")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}


