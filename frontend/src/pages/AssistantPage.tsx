import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";

import { deleteConversation, listConversations } from "../api/assistant.ts";
import { queryKeys } from "../api/queryKeys.ts";
import { AssistantChat } from "../components/assistant/AssistantChat.tsx";
import { Button } from "../components/ui/Button.tsx";
import { Card } from "../components/ui/Card.tsx";
import { PageHeader } from "../components/ui/PageHeader.tsx";
import { t } from "../i18n/t.ts";
import { cn } from "../lib/cn.ts";

/** /assistant: conversation history on the left, the chat on the right. */
export function AssistantPage() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get("conversation"));
  const selected = Number.isInteger(raw) && raw > 0 ? raw : null;
  const select = useCallback(
    (id: number | null) => setParams(id === null ? {} : { conversation: String(id) }),
    [setParams],
  );
  // A fresh chat only when the user picks a conversation or starts a new one, not when the
  // first question creates the conversation (that would cut the answer being streamed).
  const [chatKey, setChatKey] = useState(0);
  const open = useCallback(
    (id: number | null) => {
      setChatKey((k) => k + 1);
      select(id);
    },
    [select],
  );
  const conversations = useQuery({ queryKey: queryKeys.assistantConversations, queryFn: listConversations });
  const remove = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => {
      open(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.assistantConversations });
    },
  });

  return (
    <main className="flex flex-col gap-6 p-4 sm:p-6">
      <PageHeader
        title={t("assistant.title")}
        subtitle={t("assistant.subtitle")}
        actions={
          <Button onClick={() => open(null)} icon={<MessageSquarePlus className="h-5 w-5" />}>
            {t("assistant.new")}
          </Button>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <Card title={t("assistant.history")} className="self-start">
          {conversations.data?.length === 0 && <p className="text-small text-ink-muted">{t("assistant.historyEmpty")}</p>}
          <ul className="flex flex-col gap-1" data-testid="conversation-list">
            {conversations.data?.map((c) => (
              <li key={c.id} className="flex items-center gap-1">
                <button
                  type="button"
                  aria-current={c.id === selected ? "true" : undefined}
                  onClick={() => open(c.id)}
                  className={cn(
                    "min-h-11 flex-1 truncate rounded-control px-3 text-left text-small",
                    c.id === selected ? "bg-accent-soft font-semibold text-accent" : "text-ink hover:bg-surface-muted",
                  )}
                  dir="auto"
                >
                  {c.title || t("assistant.new")}
                </button>
                {c.id === selected && (
                  <button
                    type="button"
                    aria-label={t("assistant.delete")}
                    onClick={() => remove.mutate(c.id)}
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-control text-ink-muted hover:bg-surface-muted"
                  >
                    <Trash2 aria-hidden className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <AssistantChat key={chatKey} conversationId={selected} onConversation={select} />
        </Card>
      </div>
    </main>
  );
}
