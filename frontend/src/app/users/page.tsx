"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { GROUPS, ROLE_LABEL, type Role } from "@/lib/roles";

type Row = {
  username: string;
  role: Role;
  tenant: string | null;
  groups: string[];
  disabled: boolean;
  must_change_password: boolean;
  last_login: string;
};
const ROLES = Object.keys(ROLE_LABEL) as Role[];
const blank = { username: "", role: "user" as Role, tenant: "", groups: [] as string[], password: "" };

export default function UsersPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [secret, setSecret] = useState<{ username: string; password: string } | null>(null);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/users")
      .then(async (r) => ({ ok: r.ok, body: await r.json().catch(() => null) }))
      .then(({ ok, body }) => {
        if (cancelled) return;
        if (!ok) setError(body?.error ?? "Could not load accounts.");
        else {
          setError(null);
          setRows(body.accounts);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const needsTenant = form.role !== "platform_admin";
  const mode = form.role === "user" ? "multi" : form.role === "group_admin" ? "single" : "none";

  function toggleGroup(g: string) {
    setForm((f) => ({
      ...f,
      groups: mode === "single" ? [g] : f.groups.includes(g) ? f.groups.filter((x) => x !== g) : [...f.groups, g],
    }));
  }

  async function call(url: string, init: RequestInit) {
    setBusy(true);
    setError(null);
    const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...init }).catch(() => null);
    const body = await r?.json().catch(() => null);
    setBusy(false);
    if (!r || !r.ok) {
      setError(body?.error ?? "Request failed.");
      return null;
    }
    setTick((n) => n + 1);
    return body;
  }

  async function create() {
    const body = await call("/api/admin/users", {
      method: "POST",
      body: JSON.stringify({
        username: form.username,
        role: form.role,
        tenant: needsTenant ? form.tenant : null,
        groups: mode === "none" ? [] : form.groups,
        password: form.password || null,
      }),
    });
    if (!body) return;
    if (body.temporary_password) setSecret({ username: body.account.username, password: body.temporary_password });
    setForm(blank);
  }

  async function reset(username: string) {
    if (!window.confirm(`Reset the password for ${username}? Their sessions end immediately.`)) return;
    const body = await call(`/api/admin/users/${encodeURIComponent(username)}/reset-password`, { method: "POST" });
    if (body) setSecret({ username, password: body.temporary_password });
  }

  async function remove(username: string) {
    if (!window.confirm(`Delete ${username}? This cannot be undone.`)) return;
    await call(`/api/admin/users/${encodeURIComponent(username)}`, { method: "DELETE" });
  }

  const field = "rounded-md border bg-background px-3 py-1.5 text-sm";
  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Create accounts and hand out their first password. People must change it at first sign-in. Platform
          administrators manage accounts only and can&apos;t see any tenant&apos;s documents.
        </p>
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {secret && (
        <Card className="border-foreground/30">
          <CardContent className="space-y-2 pt-6 text-sm">
            <div>Temporary password for <b>{secret.username}</b>. It is shown once and can&apos;t be recovered.</div>
            <code className="block rounded bg-muted px-3 py-2 font-mono">{secret.password}</code>
            <Button size="sm" variant="outline" onClick={() => setSecret(null)}>I&apos;ve copied it</Button>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-4 pt-6">
          <h2 className="text-sm font-medium">New account</h2>
          <div className="flex flex-wrap items-center gap-3">
            <input className={field} placeholder="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            <select className={field} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role, groups: [] })}>
              {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
            {needsTenant && (
              <input className={field} placeholder="tenant, e.g. tenant-1" value={form.tenant} onChange={(e) => setForm({ ...form, tenant: e.target.value })} />
            )}
            {mode !== "none" && (
              <div className="flex items-center gap-1.5">
                {GROUPS.map((g) => (
                  <button key={g} onClick={() => toggleGroup(g)}
                    className={`rounded-full border px-3 py-1 text-xs ${form.groups.includes(g) ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"}`}>
                    {g}
                  </button>
                ))}
                <span className="text-xs text-muted-foreground">{mode === "single" ? "pick one" : "pick one or more"}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <input className={`${field} w-72`} type="password" placeholder="password (leave empty to generate one)" autoComplete="new-password"
              value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <Button onClick={create} disabled={busy || !form.username}>Create account</Button>
          </div>
        </CardContent>
      </Card>

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Username</th>
              <th className="px-4 py-3 font-medium">Role</th>
              <th className="px-4 py-3 font-medium">Tenant</th>
              <th className="px-4 py-3 font-medium">Groups</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Last sign-in</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.username} className="h-14 border-b last:border-0">
                <td className="px-4 font-mono text-xs">{a.username}</td>
                <td className="px-4 text-xs">{ROLE_LABEL[a.role]}</td>
                <td className="px-4 text-xs">{a.tenant ?? "–"}</td>
                <td className="px-4 text-xs">{a.groups.join(", ") || "–"}</td>
                <td className="px-4">
                  {a.disabled ? <Badge variant="outline">disabled</Badge>
                    : a.must_change_password ? <Badge variant="outline">must change password</Badge>
                    : <Badge variant="secondary">active</Badge>}
                </td>
                <td className="px-4 text-xs text-muted-foreground">{a.last_login ? new Date(a.last_login).toLocaleString() : "never"}</td>
                <td className="px-4 text-right">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" disabled={busy}
                      onClick={() => call(`/api/admin/users/${encodeURIComponent(a.username)}`, { method: "PATCH", body: JSON.stringify({ disabled: !a.disabled }) })}>
                      {a.disabled ? "Enable" : "Disable"}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => reset(a.username)}>Reset</Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove(a.username)}>Delete</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

