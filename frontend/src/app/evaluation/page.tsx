"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Metrics = Record<string, number>;
type EvalResponse = { report: Metrics; baseline: Metrics | null; gate_failures: string[] | null };
type Kind = "pct" | "ms" | "count";

const SECTIONS: { title: string; note: string; items: [string, string, Kind][] }[] = [
  {
    title: "Retrieval",
    note: "Did the right document come back? Document-level, over the golden queries.",
    items: [
      ["recall_at_5", "Recall@5", "pct"],
      ["recall_at_10", "Recall@10", "pct"],
      ["mrr", "MRR", "pct"],
      ["ndcg_at_10", "nDCG@10", "pct"],
      ["retrieval_latency_p95_ms", "Search p95", "ms"],
    ],
  },
  {
    title: "Answers",
    note: "Scored exactly against known answers. No model acts as judge.",
    items: [
      ["answer_correct_rate", "Correct answers", "pct"],
      ["refusal_correct_rate", "Correct refusals", "pct"],
      ["cited_relevant_rate", "Cites right document", "pct"],
      ["hallucination_rate", "Hallucination", "pct"],
      ["answer_latency_p95_ms", "Answer p95", "ms"],
    ],
  },
  {
    title: "Security",
    note: "These must be exactly zero. The gate has no tolerance for them.",
    items: [
      ["permission_violations", "Permission violations", "count"],
      ["revocation_leaks", "Revocation leaks", "count"],
      ["revocation_max_ms", "Revocation, worst case", "ms"],
    ],
  },
];

function fmt(v: number, kind: Kind) {
  if (kind === "pct") return `${(v * 100).toFixed(1)}%`;
  if (kind === "ms") return `${Math.round(v)} ms`;
  return String(v);
}

export default function EvaluationPage() {
  const [data, setData] = useState<EvalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/admin/eval")
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) setError(body?.error ?? `Request failed (${r.status})`);
        else setData(body);
      })
      .catch(() => setError("Could not reach the frontend server."));
  }, []);

  const gate = data?.gate_failures ?? null;

  return (
    <div className="max-w-4xl space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Evaluation</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            The latest run of <code className="font-mono">rag eval</code>, compared with the saved baseline.
            In CI, a drop in quality or any security failure fails the build.
          </p>
        </div>
        {data && (
          <Badge variant={gate === null ? "outline" : gate.length === 0 ? "secondary" : "destructive"}>
            {gate === null ? "no baseline" : gate.length === 0 ? "gate passed" : "gate failed"}
          </Badge>
        )}
      </header>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {gate && gate.length > 0 && (
        <ul className="list-inside list-disc text-sm text-destructive">
          {gate.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}

      {data &&
        SECTIONS.map((s) => (
          <Card key={s.title}>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {s.title} <span className="font-normal text-muted-foreground">· {s.note}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-5">
              {s.items
                .filter(([key]) => key in data.report)
                .map(([key, label, kind]) => {
                  const v = data.report[key];
                  const base = data.baseline?.[key];
                  return (
                    <div key={key}>
                      <div className="text-2xl font-semibold tabular-nums tracking-tight">{fmt(v, kind)}</div>
                      <div className="text-xs text-muted-foreground">{label}</div>
                      {base !== undefined && base !== v && (
                        <div className="text-[11px] text-muted-foreground">baseline {fmt(base, kind)}</div>
                      )}
                    </div>
                  );
                })}
            </CardContent>
          </Card>
        ))}
    </div>
  );
}


