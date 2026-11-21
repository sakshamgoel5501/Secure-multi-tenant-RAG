"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Persona } from "@/lib/personas";

type Ctx = {
  persona: Persona | null;
  select: (id: string, password?: string) => Promise<string | null>;
  refresh: () => Promise<void>;
};
const PersonaContext = createContext<Ctx>({
  persona: null,
  select: async () => null,
  refresh: async () => {},
});

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona | null>(null);

  useEffect(() => {
    fetch("/api/persona")
      .then((r) => r.json())
      .then((p) => setPersona(p?.id ? p : null))
      .catch(() => setPersona(null));
  }, []);

  const refresh = useCallback(async () => {
    const r = await fetch("/api/persona").catch(() => null);
    const p = await r?.json().catch(() => null);
    setPersona(p?.id ? p : null);
  }, []);

  /** Returns an error message, or null on success. */
  const select = useCallback(async (id: string, password?: string) => {
    const r = await fetch("/api/persona", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, password }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) return body?.error ?? "Could not switch identity.";
    setPersona(body);
    return null;
  }, []);

  return <PersonaContext.Provider value={{ persona, select, refresh }}>{children}</PersonaContext.Provider>;
}

export const usePersona = () => useContext(PersonaContext);


