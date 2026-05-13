import { AutoRefresh } from "@/components/auto-refresh";
import { Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { getBatchStatus, getModelOverview, getPipelineRunStatus, getReferenceBatchStatus, getWorkflowStatus, type WorkflowRuntimeStep } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatBytes, formatDateTime, formatDisplayValue, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";

function statusPillClass(status: string) {
  if (status === "running" || status === "completed") {
    return "live";
  }
  if (status === "failed" || status === "stalled" || status === "stopped") {
    return "warn";
  }
  return "";
}

function stepArtifact(runtime?: WorkflowRuntimeStep | null) {
  if (!runtime) {
    return null;
  }
  if (runtime.artifact_path) {
    return runtime.artifact_path;
  }
  if (runtime.latest_log_file) {
    return runtime.latest_log_file;
  }
  return "—";
}

function visibleStepDetails(stepKey: string, details: WorkflowRuntimeStep["details"]) {
  if (stepKey !== "step1") {
    return details;
  }

  const hiddenLabels = new Set([
    "Container status",
    "Progress",
    "Done / total",
    "Batch state created",
    "State updated",
    "Failed count",
    "Current pass",
    "Last code",
    "Active stocks",
    "Registry rows",
    "Kline files",
    "Valuation files",
    "Paired files",
    "Reference status",
    "Reference updated",
    "Reference ready",
    "Reference missing",
    "Reference stale",
    "Industry missing",
    "Reference batch state",
    "Reference batch updated",
    "Reference batch last code",
    "Failure reasons",
    "Last activity",
    "Stalled"
  ]);

  return details.filter((detail) => !hiddenLabels.has(detail.label));
}

function flashMessage(
  isZh: boolean,
  params: { notice?: string; error?: string; target?: string },
  stepLabels: Record<string, string>
) {
  const code = params.notice ?? params.error;
  if (!code) {
    return null;
  }

  const targetLabel = stepLabels[params.target ?? ""] ?? (isZh ? "目前控制項" : "this control");
  const success = {
    started: isZh ? `${targetLabel} 已送出啟動要求。` : `Start request sent for ${targetLabel}.`,
    stopped: isZh ? `${targetLabel} 已送出停止要求。` : `Stop request sent for ${targetLabel}.`
  } as const;
  const errors: Record<string, string> = {
    forbidden: isZh ? "這個帳號沒有控制權限。" : "This account does not have permission to control the workflow.",
    already_running: isZh ? `${targetLabel} 已經在執行中。` : `${targetLabel} is already running.`,
    not_running: isZh ? `${targetLabel} 目前沒有在執行。` : `${targetLabel} is not currently running.`,
    not_found: isZh ? `找不到 ${targetLabel} 的執行紀錄。` : `No run record was found for ${targetLabel}.`,
    control_unavailable: isZh ? "後台控制功能尚未正確設定。" : "Workflow control is not configured correctly yet.",
    invalid_action: isZh ? "這個控制動作無效。" : "That control action is not valid.",
    control_failed: isZh ? "控制要求失敗，請查看 API 日誌。" : "Control request failed. Check the API logs.",
    docker_unavailable: isZh ? "API 容器目前無法連到 Docker。" : "The API container cannot reach Docker right now.",
    image_missing: isZh ? "需要的 Docker image 不存在。" : "A required Docker image is missing.",
    batch_running: isZh ? "Step 1 或 Daily Pipeline 正在執行，請等空閒時再刷新慢變 reference data。" : "Step 1 or the daily pipeline is running. Refresh slow reference data when the system is idle.",
    start_failed: isZh ? `${targetLabel} 啟動失敗。` : `${targetLabel} failed to start.`,
    stop_failed: isZh ? `${targetLabel} 停止失敗。` : `${targetLabel} failed to stop.`,
    pipeline_running: isZh ? "Daily pipeline 執行中，請先停止它再手動啟動單一步驟。" : "Daily pipeline is running. Stop it before starting a single step manually.",
    invalid_step: isZh ? "這個 workflow step 不支援控制。" : "That workflow step is not supported by the control layer."
  };

  if (params.notice && code in success) {
    return { tone: "success", text: success[code as keyof typeof success] };
  }
  if (code in errors) {
    return { tone: "error", text: errors[code] };
  }
  if (params.notice) {
    return {
      tone: "success",
      text: isZh ? `${targetLabel} 控制作業已完成。` : `${targetLabel} control action completed.`
    };
  }
  return { tone: "error", text: errors.control_failed };
}

function renderControlButtons({
  target,
  isAdmin,
  canStart,
  canStop,
  startLabel,
  stopLabel
}: {
  target: string;
  isAdmin: boolean;
  canStart: boolean;
  canStop: boolean;
  startLabel: string;
  stopLabel: string;
}) {
  if (!isAdmin) {
    return null;
  }

  return (
    <div className="action-row">
      {canStart ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="start" />
          <button className="auth-submit action-button" type="submit">
            {startLabel}
          </button>
        </form>
      ) : null}
      {canStop ? (
        <form action="/batch/control" method="post">
          <input type="hidden" name="target" value={target} />
          <input type="hidden" name="action" value="stop" />
          <button className="action-button danger-button" type="submit">
            {stopLabel}
          </button>
        </form>
      ) : null}
    </div>
  );
}

function InfoRow({
  label,
  value
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="pipeline-info-row">
      <span className="pipeline-info-label">{label}</span>
      <strong className="pipeline-info-value">{value}</strong>
    </div>
  );
}

function WarningList({
  warnings
}: {
  warnings: string[];
}) {
  if (!warnings.length) {
    return null;
  }

  return (
    <div className="pipeline-warning-list">
      {warnings.map((warning) => (
        <p key={warning} className="pipeline-warning-row">
          {warning}
        </p>
      ))}
    </div>
  );
}

export default async function BatchPage({
  searchParams
}: {
  searchParams?: Promise<{ notice?: string; error?: string; target?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const isZh = user.locale === "zh-Hant";
  const [batchStatus, workflow, pipeline, referenceStatus] = await Promise.all([
    getBatchStatus(),
    getWorkflowStatus(),
    getPipelineRunStatus(),
    getReferenceBatchStatus()
  ]);
  const modelOverview = await getModelOverview();
  const modelProfiles = Array.isArray(modelOverview.model_profiles)
    ? modelOverview.model_profiles as Array<Record<string, unknown>>
    : [];
  const isAdmin = user.role === "admin";
  const params = (await searchParams) ?? {};
  const stepLabels: Record<string, string> = {
    pipeline: isZh ? "Daily Pipeline" : "Daily Pipeline",
    step1: isZh ? "Step 1 資料準備" : "Step 1 Data Prepare",
    step2: isZh ? "Step 2 特徵工程" : "Step 2 Feature Engineering",
    step3: isZh ? "Step 3 推論特徵" : "Step 3 Inference Features",
    step4: isZh ? "Step 4 訓練與打分" : "Step 4 Train and Score",
    step5: isZh ? "Backtest" : "Backtest",
    step6: isZh ? "自動模擬交易" : "Auto Paper Trading",
    paper: isZh ? "自動模擬交易" : "Auto Paper Trading",
    reference: isZh ? "慢變 Reference Data" : "Slow Reference Data"
  };
  const flash = flashMessage(isZh, params, stepLabels);
  const runtimeByStep = new Map(workflow.steps.map((step) => [step.step, step]));
  const runningSteps = workflow.steps.filter((step) => step.is_running).length;
  const completedStepsLabel = pipeline.completed_steps.map((key) => stepLabels[key] ?? key).join(" -> ");
  const stepCards = [
    {
      key: "step1",
      title: stepLabels.step1,
      runtime: runtimeByStep.get(1),
      canStart: !batchStatus.is_running && !pipeline.is_running,
      canStop: batchStatus.is_running,
      startLabel: isZh ? "啟動 Step 1" : "Start Step 1",
      stopLabel: isZh ? "停止 Step 1" : "Stop Step 1"
    },
    {
      key: "step2",
      title: stepLabels.step2,
      runtime: runtimeByStep.get(2),
      canStart: !runtimeByStep.get(2)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(2)?.is_running),
      startLabel: isZh ? "啟動 Step 2" : "Start Step 2",
      stopLabel: isZh ? "停止 Step 2" : "Stop Step 2"
    },
    {
      key: "step3",
      title: stepLabels.step3,
      runtime: runtimeByStep.get(3),
      canStart: !runtimeByStep.get(3)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(3)?.is_running),
      startLabel: isZh ? "啟動 Step 3" : "Start Step 3",
      stopLabel: isZh ? "停止 Step 3" : "Stop Step 3"
    },
    {
      key: "step4",
      title: stepLabels.step4,
      runtime: runtimeByStep.get(4),
      canStart: !runtimeByStep.get(4)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(4)?.is_running),
      startLabel: isZh ? "啟動 Step 4" : "Start Step 4",
      stopLabel: isZh ? "停止 Step 4" : "Stop Step 4"
    },
    {
      key: "step5",
      title: stepLabels.step5,
      runtime: runtimeByStep.get(5),
      canStart: !runtimeByStep.get(5)?.is_running && !pipeline.is_running,
      canStop: Boolean(runtimeByStep.get(5)?.is_running),
      startLabel: isZh ? "啟動 Backtest" : "Run Backtest",
      stopLabel: isZh ? "停止 Backtest" : "Stop Backtest"
    },
    {
      key: "paper",
      title: stepLabels.step6,
      runtime: runtimeByStep.get(6),
      canStart: !runtimeByStep.get(6)?.is_running,
      canStop: Boolean(runtimeByStep.get(6)?.is_running),
      startLabel: isZh ? "啟動模擬交易" : "Start Paper Trading",
      stopLabel: isZh ? "停止模擬交易" : "Stop Paper Trading"
    }
  ];

  return (
    <Shell
      title={isZh ? "Pipeline" : "Pipeline"}
      subtitle=""
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <AutoRefresh intervalSeconds={15} />
      {flash ? <p className={`banner banner-${flash.tone}`}>{flash.text}</p> : null}

      <section className="control-center-grid">
        <Panel
          title={isZh ? "Daily Pipeline" : "Daily Pipeline"}
          aside={<span className={`pill ${statusPillClass(pipeline.status)}`}>{pipeline.status_label}</span>}
        >
          <div className="stack">
            <div className="pipeline-info-list">
              <InfoRow label={isZh ? "目前步驟" : "Current step"} value={pipeline.current_step_label ?? "—"} />
              <InfoRow label={isZh ? "Step 1" : "Step 1"} value={`${formatNumber(batchStatus.done_count, user.locale)}/${formatNumber(batchStatus.total_codes, user.locale)}`} />
              <InfoRow
                label={isZh ? "進度" : "Progress"}
                value={typeof batchStatus.progress_pct === "number"
                  ? `${formatNumber(batchStatus.progress_pct, user.locale, { maximumFractionDigits: 1 })}%`
                  : "—"}
              />
              <InfoRow label={isZh ? "最新代碼" : "Last code"} value={batchStatus.last_code ?? "—"} />
              <InfoRow label={isZh ? "執行中步驟" : "Running steps"} value={formatNumber(runningSteps, user.locale)} />
              <InfoRow label={isZh ? "已完成" : "Completed"} value={completedStepsLabel || "—"} />
              <InfoRow label={isZh ? "容器" : "Container"} value={pipeline.container_name ?? "—"} />
              <InfoRow label={isZh ? "更新" : "Updated"} value={formatDateTime(pipeline.updated_at, user.locale)} />
              <InfoRow label={isZh ? "Batch 更新" : "Batch updated"} value={formatDateTime(batchStatus.updated_at, user.locale)} />
              <InfoRow label={isZh ? "日誌來源" : "Log source"} value={pipeline.log_source ?? "—"} />
            </div>
            {pipeline.error_message ? (
              <p className="panel-copy status-warn">{isZh ? `錯誤: ${pipeline.error_message}` : `Error: ${pipeline.error_message}`}</p>
            ) : null}
            {renderControlButtons({
              target: "pipeline",
              isAdmin,
              canStart: pipeline.can_start,
              canStop: pipeline.can_stop,
              startLabel: isZh ? "啟動 Daily Pipeline" : "Run Daily Pipeline",
              stopLabel: isZh ? "停止 Daily Pipeline" : "Stop Daily Pipeline"
            })}
            <pre className="log-console compact-log">{pipeline.log_lines.join("\n") || copy.common.noLogs}</pre>
          </div>
        </Panel>

        {stepCards.map((card) => (
          <Panel
            key={card.key}
            title={card.title}
            aside={<span className={`pill ${statusPillClass(card.runtime?.status ?? "idle")}`}>{card.runtime?.status_label ?? "Idle"}</span>}
          >
            <div className="stack">
              <div className="pipeline-info-list">
                <InfoRow label={isZh ? "Artifact" : "Artifact"} value={stepArtifact(card.runtime)} />
                <InfoRow label={isZh ? "大小" : "Size"} value={formatBytes(card.runtime?.artifact_size_bytes, user.locale)} />
                <InfoRow label={isZh ? "Log" : "Log"} value={card.runtime?.latest_log_source ?? "—"} />
                <InfoRow label={isZh ? "容器" : "Container"} value={card.runtime?.container_name ?? "—"} />
                {card.key !== "step1" ? (
                  <InfoRow label={isZh ? "容器狀態" : "Container status"} value={card.runtime?.container_status ?? "—"} />
                ) : null}
                <InfoRow label={isZh ? "開始" : "Started"} value={formatDateTime(card.runtime?.container_started_at, user.locale)} />
                <InfoRow label={isZh ? "完成" : "Finished"} value={formatDateTime(card.runtime?.container_finished_at, user.locale)} />
                {card.key === "step1" ? (
                  <>
                    <InfoRow label={isZh ? "進度" : "Progress"} value={`${formatNumber(batchStatus.done_count, user.locale)}/${formatNumber(batchStatus.total_codes, user.locale)}`} />
                    <InfoRow
                      label={isZh ? "進度 %" : "Progress %"}
                      value={typeof batchStatus.progress_pct === "number"
                        ? `${formatNumber(batchStatus.progress_pct, user.locale, { maximumFractionDigits: 1 })}%`
                        : "—"}
                    />
                    <InfoRow label={isZh ? "警告" : "Warnings"} value={formatNumber((card.runtime?.warnings ?? []).length, user.locale)} />
                  </>
                ) : null}
                {visibleStepDetails(card.key, card.runtime?.details ?? []).map((detail) => (
                  <InfoRow
                    key={`${card.key}-${detail.label}`}
                    label={detail.label}
                    value={formatDisplayValue(detail.value, { locale: user.locale, key: detail.label })}
                  />
                ))}
              </div>
              <WarningList warnings={card.runtime?.warnings ?? []} />
              {card.key === "step5" ? (
                <div className="action-row">
                  {isAdmin && card.canStart
                    ? modelProfiles.map((profile) => {
                        const profileName = String(profile.name ?? "").trim();
                        const profileLabel = String(profile.label ?? profileName).trim() || profileName;
                        if (!profileName) {
                          return null;
                        }
                        return (
                          <form key={profileName} action="/batch/control" method="post">
                            <input type="hidden" name="target" value={card.key} />
                            <input type="hidden" name="action" value="start" />
                            <input type="hidden" name="profile" value={profileName} />
                            <button className="auth-submit action-button" type="submit">
                              {isZh ? `回測 ${profileLabel}` : `Backtest ${profileLabel}`}
                            </button>
                          </form>
                        );
                      })
                    : null}
                  {isAdmin && card.canStop ? (
                    <form action="/batch/control" method="post">
                      <input type="hidden" name="target" value={card.key} />
                      <input type="hidden" name="action" value="stop" />
                      <button className="action-button danger-button" type="submit">
                        {card.stopLabel}
                      </button>
                    </form>
                  ) : null}
                </div>
              ) : renderControlButtons({
                target: card.key,
                isAdmin,
                canStart: card.canStart,
                canStop: card.canStop,
                startLabel: card.startLabel,
                stopLabel: card.stopLabel
              })}
              <pre className="log-console compact-log">{card.runtime?.log_lines.join("\n") || copy.common.noLogs}</pre>
            </div>
          </Panel>
        ))}

        <Panel
          title={stepLabels.reference}
          aside={<span className={`pill ${statusPillClass(referenceStatus.status)}`}>{referenceStatus.status_label}</span>}
        >
          <div className="stack">
            <div className="pipeline-info-list">
              <InfoRow label={isZh ? "進度" : "Progress"} value={`${formatNumber(referenceStatus.done_count, user.locale)}/${formatNumber(referenceStatus.total_codes, user.locale)}`} />
              <InfoRow label={isZh ? "Ready" : "Ready"} value={formatNumber(referenceStatus.valuation_reference_ready_count, user.locale)} />
              <InfoRow label={isZh ? "Stale" : "Stale"} value={formatNumber(referenceStatus.valuation_reference_stale_count, user.locale)} />
              <InfoRow label={isZh ? "Missing" : "Missing"} value={formatNumber(referenceStatus.valuation_reference_missing_count, user.locale)} />
              <InfoRow label={isZh ? "Target trade date" : "Target trade date"} value={referenceStatus.target_trade_date ?? "—"} />
              <InfoRow label={isZh ? "Last code" : "Last code"} value={referenceStatus.last_code ?? "—"} />
              <InfoRow label={isZh ? "Updated" : "Updated"} value={formatDateTime(referenceStatus.updated_at ?? referenceStatus.reference_status_updated_at, user.locale)} />
              <InfoRow label={isZh ? "Industry missing" : "Industry missing"} value={formatNumber(referenceStatus.industry_missing_count, user.locale)} />
              <InfoRow label={isZh ? "Container" : "Container"} value={referenceStatus.container_name ?? "—"} />
            </div>
            {referenceStatus.last_error ? (
              <p className="panel-copy status-warn">{isZh ? `最後錯誤: ${referenceStatus.last_error}` : `Last error: ${referenceStatus.last_error}`}</p>
            ) : null}
            {renderControlButtons({
              target: "reference",
              isAdmin,
              canStart: referenceStatus.can_start && !pipeline.is_running,
              canStop: referenceStatus.can_stop,
              startLabel: isZh ? "刷新 Reference Data" : "Refresh Reference Data",
              stopLabel: isZh ? "停止 Reference Batch" : "Stop Reference Batch"
            })}
            <pre className="log-console compact-log">{referenceStatus.log_lines.join("\n") || copy.common.noLogs}</pre>
          </div>
        </Panel>
      </section>
    </Shell>
  );
}
