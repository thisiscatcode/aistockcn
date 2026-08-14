"use client";

import { useEffect, useState } from "react";

import type { ResearchEvaluationRun, ResearchLiveQuality } from "@/lib/api";


function percent(value: number) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}


export function ResearchEvaluationPanel() {
  const [runs, setRuns] = useState<ResearchEvaluationRun[]>([]);
  const [active, setActive] = useState<ResearchEvaluationRun | null>(null);
  const [liveQuality, setLiveQuality] = useState<ResearchLiveQuality | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetch("/research/evaluations", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Unable to load evaluations")))
      .then((payload) => {
        setRuns(payload.runs ?? []);
        setLiveQuality(payload.live_quality ?? null);
      })
      .catch(() => undefined);
  }, []);

  async function runEvaluation() {
    setRunning(true);
    setError("");
    try {
      const response = await fetch("/research/evaluations", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail ?? "Evaluation run failed");
      const result = payload as ResearchEvaluationRun;
      setActive(result);
      setRuns((current) => [result, ...current.filter((item) => item.id !== result.id)]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Evaluation run failed");
    } finally {
      setRunning(false);
    }
  }

  const visible = active ?? runs[0] ?? null;
  return (
    <section className="research-evaluation-panel">
      <div className="research-section-heading">
        <div>
          <p className="research-kicker">RAG evaluation</p>
          <h2>Retrieval and live answer quality</h2>
        </div>
        <button type="button" onClick={runEvaluation} disabled={running}>
          {running ? "Scoring…" : "Run live evaluation"}
        </button>
      </div>
      {error ? <p className="research-error" role="alert">{error}</p> : null}
      {visible ? (
        <div className="research-evaluation-content">
          <div className="research-evaluation-metrics">
            <article><span>Top-1 accuracy</span><strong>{percent(visible.top1_accuracy)}</strong></article>
            <article><span>MRR</span><strong>{Number(visible.mean_reciprocal_rank).toFixed(3)}</strong></article>
            <article><span>Lexical baseline</span><strong>{percent(visible.baseline_top1_accuracy)}</strong></article>
            <article><span>Citation pass</span><strong>{liveQuality?.citation_pass_rate == null ? "—" : percent(liveQuality.citation_pass_rate)}</strong></article>
            <article><span>Answer success</span><strong>{liveQuality?.completed_rate == null ? "—" : percent(liveQuality.completed_rate)}</strong></article>
            <article><span>Degraded</span><strong>{liveQuality?.degraded_rate == null ? "—" : percent(liveQuality.degraded_rate)}</strong></article>
            <article><span>Latency p50</span><strong>{liveQuality?.latency_ms.p50 == null ? "—" : `${(liveQuality.latency_ms.p50 / 1000).toFixed(1)}s`}</strong></article>
            <article><span>Latency p95</span><strong>{liveQuality?.latency_ms.p95 == null ? "—" : `${(liveQuality.latency_ms.p95 / 1000).toFixed(1)}s`}</strong></article>
          </div>
          <p className="research-evaluation-model">
            PyTorch · {visible.model_name} · {visible.case_count} labelled ranking cases · {(visible.duration_ms / 1000).toFixed(1)}s
          </p>
          {visible.details ? (
            <div className="research-evaluation-cases">
              {visible.details.map((item) => (
                <article key={item.case} className={item.passed ? "is-passed" : "is-failed"}>
                  <span>{item.passed ? "PASS" : "MISS"}</span>
                  <strong>{item.query}</strong>
                  <small>Relevant rank {item.relevant_rank} · baseline rank {item.baseline_relevant_rank}</small>
                </article>
              ))}
            </div>
          ) : <p className="research-evaluation-hint">Run the benchmark to inspect every ranking case.</p>}
          {liveQuality?.recent_runs.length ? (
            <div className="research-live-runs">
              <div><strong>Recent grounded answers</strong><small>{liveQuality.sample_size} run quality window</small></div>
              {liveQuality.recent_runs.slice(0, 10).map((run) => (
                <article key={run.id}>
                  <strong>{run.symbols.join(" / ")}</strong>
                  <span>{run.graph_version ?? run.run_type}</span>
                  <span className={`is-${run.citation_metrics?.status ?? run.status}`}>
                    {run.citation_metrics?.status ?? run.status}
                  </span>
                  <small>{run.duration_ms == null ? "—" : `${(run.duration_ms / 1000).toFixed(1)}s`}</small>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="research-evaluation-hint">No benchmark run yet. Run it live to load the model and persist measured results.</p>
      )}
    </section>
  );
}
