export interface Criterion { id: string; title: string; description: string; max_score: number }
export interface GradingTask {
  id: string; source_site_id: string; course_id: string; assignment_id: string;
  question_id: string; title: string; subject: string; question: string;
  rubric_version: string; max_score: number; criteria: Criterion[];
}
export interface Suggestion {
  criteria: { criterion_id: string; score: number; reason: string; evidence_refs: string[] }[];
  score_suggestion: number; uncertainties: string[]; review_required: true;
}
export interface Draft {
  version: number; suggestion: Suggestion; model: string; prompt_version: string;
  rubric_version: string; review_status: string; note: string; created_at: string;
}
export interface Item {
  evidence: { submission_id: string; answer: string; quality: string;
    content_hash: string; source_locator: string; captured_at: string };
  request: { anonymous_ref: string; question: string; rubric: unknown;
    answer_lines: { ref: string; text: string }[] } | null;
  status: string; draft: Draft | null; history: Draft[]; error_code: string | null;
}
export interface Run {
  id: string; status: string; mode: 'demo' | 'school'; task: GradingTask;
  revision: number; created_at: string; items: Item[]; error_code: string | null;
}
export interface Session {
  token: string; school_enabled: boolean; cloud_enabled: boolean; retention_days: number;
  cloud_model: string; cloud_region: string; cloud_endpoint: string;
  cloud_retention_terms: string; cloud_training_terms: string;
}
