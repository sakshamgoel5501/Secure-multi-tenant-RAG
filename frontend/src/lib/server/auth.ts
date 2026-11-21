import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { SignJWT } from "jose";
import { cookies } from "next/headers";
import { DEFAULT_PERSONA_ID, findPersona, type Persona } from "@/lib/personas";

export const PERSONA_COOKIE = "rag_persona";
export const ADMIN_COOKIE = "rag_admin";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is not set (see frontend/.env.local)`);
  return v;
}

const sign = (value: string) => createHmac("sha256", env("RAG_ADMIN_KEY")).update(value).digest("hex");

export const signedAdminValue = (id: string) => `${id}.${sign(id)}`;

function verifiedAdminId(raw: string | undefined): string | undefined {
  if (!raw) return undefined;
  const i = raw.lastIndexOf(".");
  if (i < 1) return undefined;
  const id = raw.slice(0, i);
  const got = Buffer.from(raw.slice(i + 1));
  const want = Buffer.from(sign(id));
  return got.length === want.length && timingSafeEqual(got, want) ? id : undefined;
}

export function samePassword(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

/** An administrator cookie only counts if its signature verifies; otherwise the user identity applies. */
export async function currentPersona(): Promise<Persona> {
  const store = await cookies();
  const adminId = verifiedAdminId(store.get(ADMIN_COOKIE)?.value);
  const admin = adminId ? findPersona(adminId) : undefined;
  if (admin?.admin) return admin;
  return findPersona(store.get(PERSONA_COOKIE)?.value) ?? (findPersona(DEFAULT_PERSONA_ID) as Persona);
}

/** Short-lived token for a user identity. The secret never leaves the server. */
export async function mintToken(p: Persona): Promise<string> {
  if (!p.tenant || !p.group) throw new Error("not a user identity");
  const secret = new TextEncoder().encode(env("RAG_JWT_SECRET"));
  return new SignJWT({ tenant: p.tenant, groups: [p.group] })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(`demo-${p.id}`)
    .setAudience("rag")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}

/** Short-lived admin token carrying the role. The backend enforces what the role may do. */
export async function mintAdminToken(p: Persona): Promise<string> {
  if (!p.admin) throw new Error("not an administrator");
  const secret = new TextEncoder().encode(env("RAG_ADMIN_KEY"));
  const claims: Record<string, string> =
    p.admin === "platform" ? { role: "platform_admin" } : { role: "tenant_admin", tenant: p.tenant ?? "" };
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(`demo-${p.id}`)
    .setAudience("rag-admin")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret);
}


