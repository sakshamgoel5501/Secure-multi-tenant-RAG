export function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const base = process.env.BACKEND_URL ?? "http://localhost:8000";
  return fetch(base + path, { ...init, cache: "no-store" });
}

/** "embed;dur=12.3, total;dur=950.1" -> { embed: 12.3, total: 950.1 } */
export function parseServerTiming(header: string | null): Record<string, number> {
  const out: Record<string, number> = {};
  if (!header) return out;
  for (const part of header.split(",")) {
    const m = part.trim().match(/^([\w-]+);dur=([\d.]+)$/);
    if (m) out[m[1]] = Number(m[2]);
  }
  return out;
}


