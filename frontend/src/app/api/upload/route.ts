import { NextResponse } from "next/server";
import { backendFetch } from "@/lib/server/backend";
import { sessionToken } from "@/lib/server/session";

const MAX = 10 * 1000 * 1000;
const ID = /^[\w-]{1,64}$/;

export async function POST(req: Request) {
  const token = await sessionToken();
  if (!token) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const form = await req.formData().catch(() => null);
  const file = form?.get("file");
  if (!form || !(file instanceof File)) return NextResponse.json({ error: "Choose a file." }, { status: 400 });
  if (file.size > MAX) return NextResponse.json({ error: "The file is too large (limit 10 MB)." }, { status: 413 });

  const tenant = String(form.get("tenant_id") ?? "");
  const title = String(form.get("title") ?? "").trim();
  const documentId = String(form.get("document_id") ?? "");
  if (!ID.test(tenant) || !title || title.length > 200 || (documentId && !ID.test(documentId))) {
    return NextResponse.json({ error: "A title is required." }, { status: 400 });
  }

  const out = new FormData();
  out.set("file", file, "upload"); // the original file name is not forwarded
  out.set("tenant_id", tenant);
  out.set("title", title);
  if (!documentId) out.set("groups", String(form.get("groups") ?? ""));
  const path = documentId ? `/admin/documents/${documentId}/versions/upload` : "/admin/documents/upload";

  let r: Response;
  try {
    r = await backendFetch(path, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: out });
  } catch {
    return NextResponse.json({ error: "Backend unreachable. Is `rag serve --jwt --admin` running?" }, { status: 502 });
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const detail =
      r.status === 401 ? "Your session has ended. Sign in again."
      : r.status === 404 ? "The backend doesn't support file uploads yet. Restart it with the latest code."
      : typeof data?.detail === "string" ? data.detail
      : `The backend returned ${r.status}.`;
    return NextResponse.json({ error: detail }, { status: r.status });
  }
  return NextResponse.json(data);
}

