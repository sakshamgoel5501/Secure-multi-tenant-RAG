export const ACCESS_COOKIE = "rag_access";

/** What the cookie must contain. Derived from the password, so the password itself is never stored. */
export async function accessToken(password: string, secret: string): Promise<string> {
  const data = new TextEncoder().encode(`${password}:${secret}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

