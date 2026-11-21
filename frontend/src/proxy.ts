import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, accessToken } from "@/lib/access";

export async function proxy(req: NextRequest) {
  const password = process.env.APP_ACCESS_PASSWORD;
  if (!password) return NextResponse.next(); // gate off (local dev)

  const { pathname } = req.nextUrl;
  if (pathname === "/login" || pathname === "/api/login") return NextResponse.next();

  const expected = await accessToken(password, process.env.RAG_JWT_SECRET ?? "");
  if (req.cookies.get(ACCESS_COOKIE)?.value === expected) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "access password required" }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", req.url));
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };

