"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    if (!r || !r.ok) {
      setError(body?.error ?? "Could not sign in.");
      setBusy(false);
      return;
    }
    await refresh();
    router.push("/");
    router.refresh();
  }

  const field = "w-full rounded-md border bg-background px-3 py-2 text-sm";
  return (
    <div className="mx-auto mt-32 max-w-xs space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Vault</h1>
        <p className="text-sm text-muted-foreground">
          Sign in with the username and password your administrator gave you.
        </p>
      </div>
      <input className={field} placeholder="Username" autoFocus autoComplete="username" value={username}
        onChange={(e) => setUsername(e.target.value)} />
      <input className={field} type="password" placeholder="Password" autoComplete="current-password" value={password}
        onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button className="w-full" onClick={submit} disabled={busy || !username || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </div>
  );
}

