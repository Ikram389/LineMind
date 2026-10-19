import { Sparkles } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { t } from "../../i18n/t.ts";
import { formatTime } from "../../lib/time.ts";
import { Button } from "../ui/Button.tsx";
import { Drawer } from "../ui/Overlay.tsx";
import { AssistantChat } from "./AssistantChat.tsx";

interface AskAssistantProps {
  lineId: number;
  lineName: string;
  /** The range the screen shows (UTC ISO). */
  start: string | null;
  end: string | null;
  zone: string;
}

/** "Ask the assistant" button and side panel, pre-filled with the screen's line and range. */
export function AskAssistantButton({ lineId, lineName, start, end, zone }: AskAssistantProps) {
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const context = useMemo(
    () => ({ line: lineId, context_start: start, context_end: end }),
    [lineId, start, end],
  );
  const label =
    start && end
      ? t("assistant.context", { line: lineName, range: `${formatTime(start, zone)}–${formatTime(end, zone)} (${zone})` })
      : lineName;
  const close = useCallback(() => setOpen(false), []);
  return (
    <>
      <Button onClick={() => setOpen(true)} icon={<Sparkles className="h-5 w-5" />} data-testid="ask-assistant">
        {t("assistant.open")}
      </Button>
      {open && (
        <Drawer title={t("assistant.title")} subtitle={t("assistant.subtitle")} onClose={close}>
          <AssistantChat
            conversationId={conversationId}
            onConversation={setConversationId}
            context={context}
            contextLabel={label}
          />
        </Drawer>
      )}
    </>
  );
}
