import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { askQuestion, createConversation, getConversation, refusalCode } from "../../api/assistant.ts";
import type { NewConversation, UnavailableCode } from "../../api/assistantTypes.ts";
import { queryKeys } from "../../api/queryKeys.ts";

/** What is happening with the question being answered right now. */
export interface Pending {
  question: string;
  text: string;
  steps: { tool: string; label: string }[];
}

interface Options {
  conversationId: number | null;
  onConversation: (id: number) => void;
  /** Line and range the new conversation is about (side panel pre-fill). */
  context?: NewConversation;
}

/** Ask a question, stream the answer, keep the conversation cache in step. */
export function useAssistantChat({ conversationId, onConversation, context }: Options) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending | null>(null);
  const [unavailable, setUnavailable] = useState<UnavailableCode | null>(null);
  const lastQuestion = useRef("");

  const conversation = useQuery({
    queryKey: queryKeys.assistantConversation(conversationId ?? 0),
    queryFn: () => getConversation(conversationId as number),
    enabled: conversationId !== null,
  });

  const ask = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || pending) return;
      lastQuestion.current = text;
      setUnavailable(null);
      setPending({ question: text, text: "", steps: [] });
      let id = conversationId;
      try {
        if (id === null) {
          id = (await createConversation(context ?? {})).id;
          onConversation(id);
        }
        await askQuestion(id, text, (event) => {
          if (event.type === "delta") setPending((p) => p && { ...p, text: p.text + event.text });
          else if (event.type === "text_reset") setPending((p) => p && { ...p, text: "" });
          else if (event.type === "progress")
            setPending((p) => p && { ...p, steps: [...p.steps, { tool: event.tool, label: event.label }] });
          else if (event.type === "error") setUnavailable(event.code);
        });
      } catch (error) {
        setUnavailable(refusalCode(error) ?? "failed");
      } finally {
        if (id !== null) await queryClient.invalidateQueries({ queryKey: queryKeys.assistantConversation(id) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.assistantConversations });
        void queryClient.invalidateQueries({ queryKey: queryKeys.assistantStatus });
        setPending(null);
      }
    },
    [conversationId, context, onConversation, pending, queryClient],
  );

  const retry = useCallback(() => void ask(lastQuestion.current), [ask]);

  return { conversation, pending, unavailable, ask, retry };
}
