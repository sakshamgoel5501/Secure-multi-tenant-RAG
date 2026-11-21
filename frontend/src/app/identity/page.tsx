"use client";

import { Check } from "lucide-react";
import { usePersona } from "@/components/persona-provider";
import { PERSONAS } from "@/lib/personas";

export default function IdentityPage() {
  const { persona, select } = usePersona();

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Identity</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose who you are. Every page respects it, so switching identity changes what Ask can see.
          This is a demo identity picker, not authentication: the server mints a 5-minute signed
          token for the chosen persona and the backend verifies it like any other.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {PERSONAS.map((p) => {
          const active = persona?.id === p.id;
          return (
            <button
              key={p.id}
              onClick={() => select(p.id)}
              className={`rounded-lg border p-4 text-left transition-colors ${
                active ? "border-foreground/40 bg-muted" : "hover:bg-muted/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{p.label}</span>
                {active && <Check className="size-4" />}
              </div>
              <div className="mt-2 font-mono text-xs text-muted-foreground">
                tenant={p.tenant} · group={p.group}
              </div>
              {p.admin && (
                <div className="mt-1 text-xs text-muted-foreground">
                  Can upload, edit, delete and purge documents.
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

