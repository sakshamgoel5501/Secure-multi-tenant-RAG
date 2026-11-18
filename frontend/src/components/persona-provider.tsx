"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { Persona } from "@/lib/personas";

type Ctx = { persona: Persona | null; select: (id: string) => Promise<void> };
const PersonaContext = createContext<Ctx>({ persona: null, select: async () => {} });

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersona] = useState<Persona | null>(null);

  useEffect(() => {
    fetch("/api/persona")
      .then((r) => r.json())
      .then((p) => setPersona(p?.id ? p : null))
      .catch(() => setPersona(null));
  }, []);

  const select = useCallback(async (id: string) => {
    const r = await fetch("/api/persona", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    if (r.ok) setPersona(await r.json());
  }, []);

  return <PersonaContext.Provider value={{ persona, select }}>{children}</PersonaContext.Provider>;
}

export const usePersona = () => useContext(PersonaContext);


