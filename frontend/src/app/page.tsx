"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

type Report = Record<string, number>;

const IDEAS = [
  ["The index is not the authority", "Versions, deletes and access are checked against Postgres on every query, so stale vectors can never leak."],
  ["Revocation is immediate", "Remove a group from a document and its users lose it on their next request."],
  ["Failures degrade, security does not", "A slow reranker or model is skipped. An unreachable permission store returns an error, never data."],
  ["Every answer is checkable", "Citations point to exact character ranges and are validated against what was retrieved."],
];

const TOUR = [
  ["/identity", "1. Pick an identity", "Choose a tenant and group. It decides everything you can see."],
  ["/ask", "2. Ask a question", "Get a cited answer, with the source text and a timing breakdown."],
  ["/security", "3. Revoke access", "Remove a group from a document and watch it disappear for them."],
];

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

export default function HomePage() {
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    fetch("/api/admin/eval")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => setReport(b?.report ?? null))
      .catch(() => setReport(null));
  }, []);

  const pct = (v?: number) => (v === undefined ? "–" : `${(v * 100).toFixed(1)}%`);

  return (
    <div className="space-y-10">
      <header className="space-y-3 pt-6 mb-20 text-center">
        <h1 className="text-5xl font-semibold tracking-tight">Vault</h1>
        <p className="text-sm font-medium text-muted-foreground">Secure RAG · multi-tenant retrieval</p>
        <p className="mx-auto max-w-xl text-sm leading-relaxed text-muted-foreground">
          Question answering over multi-tenant documents, built so that an eventually consistent
          search index can never become a security hole. Authorization is enforced at query time from
          authoritative state.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Latest evaluation</h2>
        <Card>
          <CardContent className="pt-6">
            {report ? (
              <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                <Stat label="answers correct" value={pct(report.answer_correct_rate)} />
                <Stat label="refusals correct" value={pct(report.refusal_correct_rate)} />
                <Stat label="recall@10" value={pct(report.recall_at_10)} />
                <Stat label="permission violations" value={String(report.permission_violations ?? "–")} />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Not available. Start the backend with <code className="font-mono">rag serve --jwt --admin</code> and
                run <code className="font-mono">rag eval</code>.
              </p>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">What it guarantees</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {IDEAS.map(([title, body]) => (
            <Card key={title}>
              <CardContent className="space-y-1 pt-6">
                <div className="text-sm font-medium">{title}</div>
                <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Try it in three steps</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {TOUR.map(([href, title, body]) => (
            <Link key={href} href={href} className="group rounded-lg border p-4 transition-colors hover:bg-muted/50">
              <div className="flex items-center justify-between text-sm font-medium">
                {title}
                <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{body}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

