"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (r.ok) window.location.href = "/";
    else setError("Wrong password.");
  }

  return (
    <div className="mx-auto mt-32 max-w-xs space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Secure RAG</h1>
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

