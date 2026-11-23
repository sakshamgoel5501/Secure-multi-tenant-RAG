import { cookies } from "next/headers";

export const SESSION_COOKIE = "vault_session";

export async function sessionToken(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}

export const cookieOptions = (maxAge: number) => ({
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  secure: process.env.APP_COOKIE_SECURE === "1",
  maxAge,
});

