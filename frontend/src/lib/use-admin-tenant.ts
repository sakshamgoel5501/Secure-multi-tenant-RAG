"use client";

import { useState } from "react";
import { usePersona } from "@/components/persona-provider";
import { allowedTenants } from "@/lib/personas";

/** The tenant an administrator is currently working on, limited to what their role allows. */
export function useAdminTenant() {
  const { persona } = usePersona();
  const allowed = allowedTenants(persona);
  const [chosen, setChosen] = useState<string | null>(null);
  const tenant = chosen && allowed.includes(chosen) ? chosen : (allowed[0] ?? null);
  return { tenant, allowed, setTenant: setChosen };
}

