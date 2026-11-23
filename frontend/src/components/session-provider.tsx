"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Account } from "@/lib/roles";

type Ctx = {
  account: Account | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};
const SessionContext = createContext<Ctx>({
  account: null,
  loading: true,
  refresh: async () => {},
  signOut: async () => {},
});

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/me")
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        setAccount(ok && body?.username ? body : null);
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    const r = await fetch("/api/auth/me").catch(() => null);
    const body = await r?.json().catch(() => null);
    setAccount(r?.ok && body?.username ? body : null);
    setLoading(false);
  }, []);

  const signOut = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    setAccount(null);
  }, []);

  return <SessionContext.Provider value={{ account, loading, refresh, signOut }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);

