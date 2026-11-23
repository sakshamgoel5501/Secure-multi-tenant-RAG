"use client";

import { useState } from "react";
import { LoadingDots } from "@/components/loading-dots";
import { useSession } from "@/components/session-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { readEvents } from "@/lib/sse";

type Source = {
  marker: string;
  chunk_id: string;
  document_id: string;
  version: number;
  title: string;
  start_offset: number;
  end_offset: number;
  text: string;
};
type Final = {
  answer: string;
  grounded: boolean;
  degraded: string[];
  plan: string[];
  citations: { marker: string }[];
  timing: { first_token_ms: number | null; total_ms: number };
};
type Phase = "idle" | "searching" | "answering" | "done";

const EXAMPLES = [
  "What is the team size for project amber-falcon-0?",
  "Which project is tracked by ticket TKT-1000 and which project is tracked by ticket TKT-1003?",
  "What is the annual budget for project amber-falcon-0?",
];

function AnswerText({ text, live }: { text: string; live: boolean }) {
  return (
    <p className="leading-relaxed">
      {text.split(/(\[S\d+\])/g).map((part, i) =>
        /^\[S\d+\]$/.test(part) ? (
          <span key={i} className="mx-0.5 rounded bg-muted px-1 text-xs font-medium text-muted-foreground">
            {part.slice(1, -1)}
          </span>
        ) : (
          part
        ),
      )}
      {live && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-middle" />}
    </p>
  );
}

export default function AskPage() {
  const { account } = useSession();
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [plan, setPlan] = useState<string[]>([]);
  const [final, setFinal] = useState<Final | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = phase === "searching" || phase === "answering";

  async function submit(q: string = question) {
    if (!q.trim() || busy) return;
    setError(null);
    setText("");
    setSources([]);
    setPlan([]);
    setFinal(null);
    setPhase("searching");
    try {
      const r = await fetch("/api/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      if (!r.ok || !r.body) {
        const b = await r.json().catch(() => null);
        setError(b?.error ?? `Request failed (${r.status})`);
        setPhase("idle");
        return;
      }
      for await (const { event, data } of readEvents(r.body)) {
        if (event === "sources") {
          const d = data as { sources: Source[]; plan: string[] };
          setSources(d.sources);
          setPlan(d.plan);
          setPhase("answering");
        } else if (event === "delta") {
          setText((t) => t + (data as { text: string }).text);
        } else if (event === "final") {
          setFinal(data as Final);
          setPhase("done");
        }
      }
      setPhase((p) => (p === "done" ? p : "idle"));
    } catch {
      setError("The connection was interrupted.");
      setPhase("idle");
    }
  }

  const shown = final ? final.answer : text;
  const cited = final ? sources.filter((s) => final.citations.some((c) => c.marker === s.marker)) : [];

  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">Ask</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Answers come only from documents <span className="font-medium text-foreground">{account?.username ?? "…"}</span>{" "}
          may read, with citations you can check against the source text. Questions with several parts are split and
          searched separately.
        </p>
      </header>

      <div className="space-y-3">
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="Ask a question about the documents…"
          rows={3}
        />
        <div className="flex items-center justify-between gap-4">
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuestion(ex);
                  submit(ex);
                }}
                className="rounded-full border px-3 py-1 text-left text-xs text-muted-foreground hover:bg-muted/60"
              >
                {ex}
              </button>
            ))}
          </div>
          <Button onClick={() => submit()} disabled={busy || !question.trim()}>
            {busy ? "Working…" : "Ask"}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="pt-6 text-sm">
            <span className="font-medium">Request failed.</span> {error}
          </CardContent>
        </Card>
      )}

      {phase === "searching" && <LoadingDots label="Searching" />}

      {phase !== "idle" && phase !== "searching" && (
        <div className="space-y-4">
          {plan.length > 1 && (
            <p className="text-xs text-muted-foreground">
              Split into {plan.length} searches: {plan.map((p) => `“${p}”`).join(" · ")}
            </p>
          )}
          <Card>
            <CardContent className="space-y-4 pt-6">
              {shown ? (
                <AnswerText text={shown} live={phase === "answering"} />
              ) : (
                <LoadingDots label="Writing the answer" />
              )}
              {final && (
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={final.grounded ? "default" : "secondary"}>
                    {final.grounded ? "grounded" : "not grounded"}
                  </Badge>
                  {final.degraded.map((d) => (
                    <Badge key={d} variant="outline">degraded: {d}</Badge>
                  ))}
                  <span className="text-xs text-muted-foreground">
                    {final.timing.first_token_ms !== null && `first words after ${Math.round(final.timing.first_token_ms)} ms · `}
                    done in {Math.round(final.timing.total_ms)} ms
                  </span>
                </div>
              )}
              {!final && sources.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Found {sources.length} passage{sources.length === 1 ? "" : "s"}. Citations are checked when the answer is complete.
                </p>
              )}
            </CardContent>
          </Card>

          {cited.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-sm font-medium">Sources</h2>
              {cited.map((s) => (
                <Card key={s.chunk_id}>
                  <CardContent className="space-y-2 pt-6">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>
                        <span className="mr-2 rounded bg-muted px-1 font-medium">{s.marker}</span>
                        {s.title}
                      </span>
                      <span className="font-mono">
                        {s.document_id} v{s.version} · chars {s.start_offset}–{s.end_offset}
                      </span>
                    </div>
                    <p className="text-sm leading-relaxed">{s.text}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

