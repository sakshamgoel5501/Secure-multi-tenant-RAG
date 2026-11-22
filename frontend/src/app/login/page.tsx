"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { usePersona } from "@/components/persona-provider";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const { refresh } = usePersona();

  async function submit() {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (r.ok) {
      await refresh();
      router.push("/");
      router.refresh();
    }
    else { const b = await r.json().catch(() => null); setError(b?.error ?? "Wrong password."); }
  }

  return (
    <div className="mx-auto mt-32 max-w-xs space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Vault</h1>
        <p className="text-sm text-muted-foreground">Enter the access password to continue.</p>
      </div>
      <input
        type="password"
        value={password}
        autoFocus
        onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        className="w-full rounded-md border bg-background px-3 py-2 text-sm"
      />
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button className="w-full" onClick={submit} disabled={!password}>
        Continue
      </Button>
    </div>
  );
}

