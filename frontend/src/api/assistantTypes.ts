/** The AI assistant's API shapes (backend apps/assistant). */

export type AnswerStatus = "ok" | "busy" | "unreachable" | "timeout" | "tool_limit" | "failed";

/** Why the assistant can't answer right now (the four "unavailable" states, plus failures). */
export type UnavailableCode =
  | "disabled"
  | "unreachable"
  | "no_tool_calling"
  | "busy"
  | "daily_limit"
  | "timeout"
  | "tool_limit"
  | "invalid_tool_calls"
  | "failed";

export interface AssistantStatus {
  enabled: boolean;
  daily_limit: number;
  questions_today: number;
  model: string | null;
  reachable: boolean | null;
  tool_calling: boolean | null;
  error: string;
}

export type SourceType = "line" | "downtime" | "incident" | "quality" | "maintenance_action" | "alert" | "machine";

export interface AnswerSource {
  n: number;
  type: SourceType;
  id: number | null;
  label: string;
  link: string;
}

export interface KeyMetric {
  label: string;
  value: number | string | null;
  unit: string;
}

export interface CheckedNumber {
  text: string;
  start: number;
  end: number;
  status: "verified" | "from_question" | "unverified";
}

export interface NumberCheck {
  items: CheckedNumber[];
  verified: number;
  from_question: number;
  unverified: number;
}

export interface ToolCallTrace {
  order: number;
  name: string;
  arguments: Record<string, unknown>;
  invalid: boolean;
  error: string;
  duration_ms: number;
}

export interface AssistantMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: AnswerStatus;
  language: string;
  resolved_ranges: { start: string; end: string; label: string }[];
  sources: AnswerSource[];
  key_metrics: KeyMetric[];
  warnings: string[];
  number_check: NumberCheck | Record<string, never>;
  model: string;
  duration_ms: number | null;
  created_at: string;
  tool_calls: ToolCallTrace[];
  feedback: { helpful: boolean; comment: string } | null;
}

export interface ConversationSummary {
  id: number;
  title: string;
  line: number | null;
  line_name: string | null;
  context_start: string | null;
  context_end: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: AssistantMessage[];
}

export interface NewConversation {
  line?: number | null;
  context_start?: string | null;
  context_end?: string | null;
}

/** Events of the answer stream. */
export type StreamEvent =
  | { type: "progress"; tool: string; label: string }
  | { type: "delta"; text: string }
  | { type: "text_reset" }
  | { type: "final"; answer: AssistantMessage }
  | { type: "error"; code: UnavailableCode; message: string; answer: AssistantMessage | null };
