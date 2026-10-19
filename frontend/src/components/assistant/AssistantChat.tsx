import { useQuery } from "@tanstack/react-query";
import { CircleCheck, LoaderCircle, Lock, PlugZap, Send, Timer, UserRound, Hourglass } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useId, useState } from "react";

import { getAssistantStatus } from "../../api/assistant.ts";
import type { AssistantMessage, NewConversation, UnavailableCode } from "../../api/assistantTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";
import type { MessageKey } from "../../i18n/en.ts";
import { t } from "../../i18n/t.ts";
import { cn } from "../../lib/cn.ts";
import { Button } from "../ui/Button.tsx";
import { EmptyState, InlineNotice, Skeleton } from "../ui/Feedback.tsx";
import { AnswerCard } from "./AnswerCard.tsx";
import { AnswerText } from "./AnswerText.tsx";
import { progressLabel } from "./progress.ts";
import type { Pending } from "./useAssistantChat.ts";
import { useAssistantChat } from "./useAssistantChat.ts";

const SUGGESTIONS: MessageKey[] = [
  "assistant.suggest.1",
  "assistant.suggest.2",
  "assistant.suggest.3",
  "assistant.suggest.4",
  "assistant.suggest.5",
];

/** The four states in which the assistant cannot answer; others are shown as a notice. */
const BLOCKING = {
  disabled: Lock,
  unreachable: PlugZap,
  busy: Hourglass,
  daily_limit: Timer,
} as const;
type BlockingCode = keyof typeof BLOCKING;

function blockingCode(code: UnavailableCode | null): BlockingCode | null {
  if (code === "no_tool_calling") return "unreachable";
  return code && code in BLOCKING ? (code as BlockingCode) : null;
}

export function Unavailable({ code, limit, onRetry }: { code: BlockingCode; limit?: number; onRetry?: () => void }) {
  return (
    <div data-testid={`unavailable-${code}`} role="status">
      <EmptyState
        icon={BLOCKING[code]}
        title={t(`assistant.unavailable.${code}.title` as MessageKey)}
        text={t(`assistant.unavailable.${code}.text` as MessageKey, { limit: limit ?? 0 })}
        action={onRetry && <Button onClick={onRetry}>{t("assistant.retry")}</Button>}
      />
    </div>
  );
}

function Question({ text }: { text: string }) {
  return (
    <div className="flex items-start justify-end gap-2">
      <p className="max-w-[85%] rounded-card bg-accent-soft px-4 py-2 text-body text-ink" dir="auto">
        <span className="sr-only">{t("assistant.you")}: </span>
        {text}
      </p>
      <UserRound aria-hidden className="mt-2 h-5 w-5 shrink-0 text-ink-muted" />
    </div>
  );
}

function Failure({ message }: { message: AssistantMessage }) {
  return (
    <div data-testid="answer-failed">
      <InlineNotice tone="warning">{message.content}</InlineNotice>
    </div>
  );
}

interface AssistantChatProps {
  conversationId: number | null;
  onConversation: (id: number) => void;
  context?: NewConversation;
  /** e.g. "About Bottling Line 1 · 06:00–14:00" in the side panel. */
  contextLabel?: string;
}

/** The chat: earlier answers, the one being streamed, the question box. */
export function AssistantChat({ conversationId, onConversation, context, contextLabel }: AssistantChatProps) {
  const inputId = useId();
  const [draft, setDraft] = useState("");
  const status = useQuery({ queryKey: queryKeys.assistantStatus, queryFn: () => getAssistantStatus() });
  const chat = useAssistantChat({ conversationId, onConversation, context });
  const stored = chat.conversation.data?.messages ?? [];
  // While answering, the question is shown with the stream (not twice).
  const last = stored[stored.length - 1];
  const messages =
    chat.pending && last?.role === "user" && last.content === chat.pending.question ? stored.slice(0, -1) : stored;

  if (status.isLoading) return <Skeleton lines={4} />;
  const s = status.data;
  if (s && !s.enabled) return <Unavailable code="disabled" />;

  let blocked = blockingCode(chat.unavailable);
  if (!blocked && s?.reachable === false) blocked = "unreachable";
  if (!blocked && s && s.questions_today >= s.daily_limit) blocked = "daily_limit";
  const canAsk = !chat.pending && blocked !== "disabled" && blocked !== "daily_limit" && blocked !== "unreachable";

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canAsk) return;
    void chat.ask(draft);
    setDraft("");
  }
  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  }

  return (
    <div className="flex flex-col gap-4">
      {contextLabel && (
        <p data-testid="assistant-context" className="self-start rounded-full bg-surface-muted px-3 py-1 text-small font-semibold text-ink-muted">
          {contextLabel}
        </p>
      )}

      <ol className="flex flex-col gap-4" aria-live="polite">
        {messages.map((message) => (
          <li key={message.id}>
            {message.role === "user" ? (
              <Question text={message.content} />
            ) : message.status === "ok" ? (
              <AnswerCard answer={message} conversationId={conversationId as number} />
            ) : (
              <Failure message={message} />
            )}
          </li>
        ))}
        {chat.pending && (
          <li className="flex flex-col gap-4">
            <Question text={chat.pending.question} />
            <div data-testid="streaming" className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
              <ul className="flex flex-col gap-1">
                {chat.pending.steps.map((step, i, steps) => {
                  const done = i < steps.length - 1 || (chat.pending as Pending).text.length > 0;
                  return (
                    <li key={`${step.tool}-${i}`} className="flex items-center gap-2 text-small text-ink-muted">
                      {done ? (
                        <CircleCheck aria-hidden className="h-4 w-4 text-running" />
                      ) : (
                        <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
                      )}
                      {progressLabel(step.tool, step.label)}
                    </li>
                  );
                })}
                {chat.pending.steps.length === 0 && !chat.pending.text && (
                  <li className="flex items-center gap-2 text-small text-ink-muted">
                    <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
                    {t("assistant.thinking")}
                  </li>
                )}
              </ul>
              {chat.pending.text && <AnswerText content={chat.pending.text} />}
            </div>
          </li>
        )}
      </ol>

      {blocked && (
        <Unavailable
          code={blocked}
          limit={s?.daily_limit}
          onRetry={blocked === "busy" ? chat.retry : blocked === "unreachable" ? () => void status.refetch() : undefined}
        />
      )}
      {!blocked && chat.unavailable && (
        <InlineNotice tone="warning">{t("panel.error")}</InlineNotice>
      )}

      {messages.length === 0 && !chat.pending && canAsk && (
        <section aria-label={t("assistant.suggested")} className="flex flex-col gap-2">
          <p className="text-small font-semibold text-ink-muted">{t("assistant.suggested")}</p>
          <ul className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((key) => (
              <li key={key}>
                <button
                  type="button"
                  onClick={() => void chat.ask(t(key))}
                  className="min-h-11 rounded-full border border-line-strong bg-surface px-4 text-left text-small text-ink hover:border-accent hover:text-accent"
                >
                  {t(key)}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <label htmlFor={inputId} className="sr-only">
          {t("assistant.inputLabel")}
        </label>
        <textarea
          id={inputId}
          rows={2}
          value={draft}
          dir="auto"
          disabled={!canAsk}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder={t("assistant.placeholder")}
          className={cn(
            "min-h-14 flex-1 resize-y rounded-control border border-line-strong bg-surface px-3 py-2 text-body text-ink placeholder:text-ink-muted",
            "disabled:opacity-60",
          )}
        />
        <Button type="submit" variant="primary" size="lg" disabled={!canAsk || !draft.trim()} icon={<Send className="h-5 w-5" />}>
          {chat.pending ? t("assistant.asking") : t("assistant.ask")}
        </Button>
      </form>
    </div>
  );
}
