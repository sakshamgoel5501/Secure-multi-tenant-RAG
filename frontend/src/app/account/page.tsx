"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/components/session-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ROLE_LABEL } from "@/lib/roles";

export default function AccountPage() {
  const router = useRouter();
  const { account, refresh } = useSession();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function change() {
    setError(null);
    setDone(false);
    if (next !== confirm) return setError("The new passwords don't match.");
    setBusy(true);
    const r = await fetch("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: next }),
    }).catch(() => null);
    const body = await r?.json().catch(() => null);
    setBusy(false);
    if (!r || !r.ok) return setError(body?.error ?? "Could not change the password.");
    setCurrent("");
    setNext("");
    setConfirm("");
    setDone(true);
    await refresh();
    if (account?.must_change_password) router.push("/");
  }

  if (!account) return null;
  const field = "w-full max-w-sm rounded-md border bg-background px-3 py-2 text-sm";
  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Account</h1>
        {account.must_change_password && (
          <p className="mt-2 rounded-md border p-3 text-sm">Choose a new password to continue. Until you do, the rest of the app is locked.</p>
        )}
      </header>

      <Card>
        <CardContent className="grid grid-cols-[8rem_1fr] gap-y-1.5 pt-6 text-sm">
          <span className="text-muted-foreground">Username</span><span className="font-mono">{account.username}</span>
          <span className="text-muted-foreground">Role</span><span>{ROLE_LABEL[account.role]}</span>
          <span className="text-muted-foreground">Tenant</span><span>{account.tenant ?? "none (platform)"}</span>
          <span className="text-muted-foreground">Groups</span><span>{account.groups.join(", ") || "none"}</span>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-medium">Change password</h2>
          <input className={field} type="password" placeholder="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          <input className={field} type="password" placeholder="New password (12 or more characters)" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
          <input className={field} type="password" placeholder="Repeat the new password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {error && <p className="text-sm text-destructive">{error}</p>}
          {done && <p className="text-sm text-muted-foreground">Password changed. Other sessions of yours were signed out.</p>}
          <Button onClick={change} disabled={busy || !current || !next || !confirm}>Change password</Button>
        </CardContent>
      </Card>
    </div>
  );
}

