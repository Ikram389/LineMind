import type {
  AssistantMessage,
  AssistantStatus,
  ConversationDetail,
  ConversationSummary,
  NewConversation,
  StreamEvent,
  UnavailableCode,
} from "./assistantTypes.ts";
import { ApiError, apiFetch, apiStream } from "./client.ts";

const BASE = "/assistant";

export const getAssistantStatus = (refresh = false): Promise<AssistantStatus> =>
  apiFetch<AssistantStatus>(`${BASE}/status/${refresh ? "?refresh=1" : ""}`);

export const listConversations = (): Promise<ConversationSummary[]> =>
  apiFetch<ConversationSummary[]>(`${BASE}/conversations/`);

export const getConversation = (id: number): Promise<ConversationDetail> =>
  apiFetch<ConversationDetail>(`${BASE}/conversations/${id}/`);

export const createConversation = (body: NewConversation): Promise<ConversationSummary> =>
  apiFetch<ConversationSummary>(`${BASE}/conversations/`, { method: "POST", body: JSON.stringify(body) });

export const deleteConversation = (id: number): Promise<null> =>
  apiFetch<null>(`${BASE}/conversations/${id}/`, { method: "DELETE" });

export const sendFeedback = (messageId: number, helpful: boolean, comment = ""): Promise<AssistantMessage> =>
  apiFetch<AssistantMessage>(`${BASE}/messages/${messageId}/feedback/`, {
    method: "POST",
    body: JSON.stringify({ helpful, comment }),
  });

/** One server-sent event block → our event type. */
function parseBlock(block: string): StreamEvent | null {
  let name = "";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!name || !data) return null;
  const body = JSON.parse(data) as Record<string, unknown>;
  switch (name) {
    case "progress":
      return { type: "progress", tool: String(body.tool), label: String(body.label) };
    case "delta":
      return { type: "delta", text: String(body.text) };
    case "text_reset":
      return { type: "text_reset" };
    case "final":
      return { type: "final", answer: body as unknown as AssistantMessage };
    case "error":
      return {
        type: "error",
        code: body.code as UnavailableCode,
        message: String(body.message),
        answer: (body.answer as AssistantMessage | undefined) ?? null,
      };
    default:
      return null;
  }
}

/** Refusals before the stream starts (assistant off, daily limit) have an error code. */
export function refusalCode(error: unknown): UnavailableCode | null {
  if (!(error instanceof ApiError)) return null;
  const body = error.body as { code?: string } | null;
  if (body?.code === "disabled" || body?.code === "daily_limit") return body.code;
  return error.status >= 500 ? "failed" : null;
}

/** Ask a question; `onEvent` gets progress, text pieces and the final answer as they arrive. */
export async function askQuestion(
  conversationId: number,
  question: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiStream(
    `${BASE}/conversations/${conversationId}/ask/`,
    { method: "POST", body: JSON.stringify({ question }) },
    signal,
  );
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut !== -1) {
      const event = parseBlock(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (event) onEvent(event);
      cut = buffer.indexOf("\n\n");
    }
  }
  const last = parseBlock(buffer);
  if (last) onEvent(last);
}
