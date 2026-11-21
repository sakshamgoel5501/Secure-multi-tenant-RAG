"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { usePersona } from "@/components/persona-provider";
import { GROUPS, PERSONAS, TENANTS, type Persona } from "@/lib/personas";

const ADMINS = PERSONAS.filter((p) => p.admin);
const BLURB: Record<string, string> = {
  platform: "All tenants. Manages documents and access, and sees health, evaluation and the audit log.",
  tenant: "Manages this tenant only. Cannot reach other tenants or the platform pages.",
};

export default function IdentityPage() {
  const { persona, select } = usePersona();
  const [adminOn, setAdminOn] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin-status")
      .then((r) => r.json())
      .then((b) => {
        if (!cancelled) setAdminOn(Boolean(b?.enabled));
      })
      .catch(() => {
        if (!cancelled) setAdminOn(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function pick(p: Persona) {
    setError(null);
    const err = await select(p.id, p.admin ? password : undefined);
    if (err) setError(err);
  }

  const card = (p: Persona, body: React.ReactNode) => {
    const active = persona?.id === p.id;
    return (
      <button
        key={p.id}
        onClick={() => pick(p)}
        className={`rounded-lg border p-4 text-left transition-colors ${
          active ? "border-foreground/40 bg-muted" : "hover:bg-muted/50"
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{p.label}</span>
          {active && <Check className="size-4" />}
        </div>
        {body}
      </button>
    );
  };

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Identity</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose who you are. Every page respects it. This is a demo identity picker, not
          authentication: the server mints a 5-minute signed token for the chosen identity and the
          backend verifies it like any other.
        </p>
      </header>

      <section className="space-y-4">
        <h2 className="text-sm font-medium">People</h2>
        {TENANTS.map((tenant) => (
          <div key={tenant} className="space-y-2">
            <div className="text-xs text-muted-foreground">{tenant}</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {PERSONAS.filter((p) => !p.admin && p.tenant === tenant).map((p) =>
                card(
                  p,
                  <div className="mt-1 font-mono text-xs text-muted-foreground">group={p.group}</div>,
                ),
              )}
            </div>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Groups: {GROUPS.join(", ")}.</p>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Administrators</h2>
        {adminOn ? (
          <>
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Admin password"
                className="w-64 rounded-md border bg-background px-3 py-1.5 text-sm"
              />
              <span className="text-xs text-muted-foreground">Needed once per admin identity you pick.</span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {ADMINS.map((p) =>
                card(p, <div className="mt-1 text-xs text-muted-foreground">{BLURB[p.admin as string]}</div>),
              )}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            {adminOn === null ? "Checking…" : "Administrator identities are not enabled."}
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </section>
    </div>
  );
}

