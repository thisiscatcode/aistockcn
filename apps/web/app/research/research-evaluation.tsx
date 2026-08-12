"use client";

import { useEffect, useState } from "react";

import type { ResearchEvaluationRun } from "@/lib/api";


function percent(value: number) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}


export function ResearchEvaluationPanel() {
  const [runs, setRuns] = useState<ResearchEvaluationRun[]>([]);
  const [active, setActive] = useState<ResearchEvaluationRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetch("/research/evaluations", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Unable to load evaluations")))
      .then((payload) => setRuns(payload.runs ?? []))
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
          <p className="research-kicker">Retrieval evaluation</p>
          <h2>PyTorch cross-encoder benchmark</h2>
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
            <article><span>Cases / runtime</span><strong>{visible.case_count} / {(visible.duration_ms / 1000).toFixed(1)}s</strong></article>
          </div>
          <p className="research-evaluation-model">
            {visible.framework ?? "PyTorch"} {visible.torch_version ?? ""} · {visible.model_name}
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
        </div>
      ) : (
        <p className="research-evaluation-hint">No benchmark run yet. Run it live to load the model and persist measured results.</p>
      )}
    </section>
  );
}
