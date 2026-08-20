import type { ResearchAnswer } from "../../lib/api.ts";


const EMPTY_INFERENCE_MESSAGES = new Set([
  "no additional inference was required",
  "no additional inference was required.",
]);


export function isMeaningfulInference(value: string) {
  const normalized = value.trim().toLowerCase();
  return Boolean(normalized) && !EMPTY_INFERENCE_MESSAGES.has(normalized);
}


export function documentEvidenceHref(item: ResearchAnswer["document_evidence"][number]) {
  if (item.document_id && item.page_number) {
    return `/research/documents/${encodeURIComponent(item.document_id)}/file#page=${item.page_number}`;
  }
  return item.source_url ?? null;
}


export function presentationSourceHref(
  source: NonNullable<ResearchAnswer["presentation"]>["sources"][number]
) {
  if (source.document_id && source.page_number) {
    return `/research/documents/${encodeURIComponent(source.document_id)}/file#page=${source.page_number}`;
  }
  return source.source_url ?? null;
}


export function buildResearchAnswerView(answer: ResearchAnswer) {
  const presentation = answer.presentation;
  const interpretations = presentation?.interpretations ?? answer.model_inference
    .filter(isMeaningfulInference)
    .map((text) => ({ kind: "model_inference" as const, text }));
  return {
    takeaway: presentation?.takeaway || answer.answer,
    metrics: presentation?.metrics ?? [],
    interpretations,
    sources: presentation?.sources ?? [],
    showInterpretation: interpretations.length > 0,
    showFinancialTrend: Boolean(presentation?.metrics.length),
    showAdvancedAudit: true,
  };
}
