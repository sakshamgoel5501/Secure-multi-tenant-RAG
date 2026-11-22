type Entry = { fails: number; windowStart: number; lockedUntil: number };

const holder = globalThis as unknown as { __rateLimits?: Map<string, Entry> };
const store = (holder.__rateLimits ??= new Map<string, Entry>());

const WINDOW_MS = 15 * 60_000;
const LOCK_MS = 15 * 60_000;
const PER_CLIENT = 5;
const PER_BUCKET = 30; // all clients together, so rotating addresses doesn't bypass the limit

/** First address in X-Forwarded-For (Caddy sets it), or "local" when there is no proxy. */
export function clientKey(req: Request): string {
  return req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "local";
}

function get(key: string, now: number): Entry {
  const e = store.get(key);
  if (e) {
    const lockExpired = e.lockedUntil !== 0 && e.lockedUntil <= now;
    if (!lockExpired && (now - e.windowStart <= WINDOW_MS || e.lockedUntil > now)) return e;
  }
  if (store.size > 5000) {
    for (const [k, v] of store) if (v.lockedUntil <= now && now - v.windowStart > WINDOW_MS) store.delete(k);
  }
  const fresh: Entry = { fails: 0, windowStart: now, lockedUntil: 0 };
  store.set(key, fresh);
  return fresh;
}

const keys = (bucket: string, req: Request) =>
  [
    [`${bucket}:${clientKey(req)}`, PER_CLIENT],
    [`${bucket}:*`, PER_BUCKET],
  ] as const;

/** Seconds the caller must wait before trying again, or 0 if they may try. */
export function lockedFor(bucket: string, req: Request): number {
  const now = Date.now();
  const waits = keys(bucket, req).map(([k]) => Math.max(0, get(k, now).lockedUntil - now));
  return Math.ceil(Math.max(...waits) / 1000);
}

export function recordFailure(bucket: string, req: Request): void {
  const now = Date.now();
  for (const [k, max] of keys(bucket, req)) {
    const e = get(k, now);
    e.fails += 1;
    if (e.fails >= max) e.lockedUntil = now + LOCK_MS;
  }
}

export function recordSuccess(bucket: string, req: Request): void {
  store.delete(`${bucket}:${clientKey(req)}`);
}

