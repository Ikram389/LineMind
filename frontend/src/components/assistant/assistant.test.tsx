import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../api/assistant.ts";
import { askQuestion } from "../../api/assistant.ts";
import type { AssistantMessage, AssistantStatus, StreamEvent } from "../../api/assistantTypes.ts";
import * as client from "../../api/client.ts";
import { ApiError } from "../../api/client.ts";
import { renderWithProviders } from "../../test/render.tsx";
import { AnswerCard } from "./AnswerCard.tsx";
import { AskAssistantButton } from "./AssistantPanel.tsx";
import { AssistantChat } from "./AssistantChat.tsx";

const STATUS: AssistantStatus = {
  enabled: true,
  daily_limit: 30,
  questions_today: 0,
  model: "openai/gpt-oss-120b",
  reachable: true,
  tool_calling: true,
  error: "",
};

function answer(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  const content = "Mon 12 Oct: the line lost 12.5 min in 3 stops; OEE was 85% and 99% [1].";
  const at = (text: string) => content.indexOf(text);
  return {
    id: 42,
    role: "assistant",
    content,
    status: "ok",
    language: "en",
    resolved_ranges: [{ start: "2026-10-12T10:00:00Z", end: "2026-10-12T10:15:00Z", label: "Mon 12 Oct 2026 10:00–10:15 (UTC)" }],
    sources: [
      { n: 1, type: "downtime", id: null, label: "Downtime · Bottling Line", link: "/lines/1/downtime?start=2026-10-12T10%3A00%3A00Z" },
      { n: 2, type: "incident", id: 14, label: "Line stop #14", link: "/lines/1/downtime?incident=14" },
      { n: 3, type: "maintenance_action", id: 7, label: "Action #7", link: "/maintenance/7" },
    ],
    key_metrics: [{ label: "Downtime", value: 12.5, unit: "min" }],
    warnings: ["Lost bottles are estimates: stop duration x nominal speed."],
    number_check: {
      items: [
        { text: "12.5", start: at("12.5"), end: at("12.5") + 4, status: "verified" },
        { text: "85", start: at("85"), end: at("85") + 2, status: "from_question" },
        { text: "99", start: at("99"), end: at("99") + 2, status: "unverified" },
      ],
      verified: 1,
      from_question: 1,
      unverified: 1,
    },
    model: "openai/gpt-oss-120b",
    duration_ms: 2300,
    created_at: "2026-10-12T11:00:00Z",
    tool_calls: [{ order: 1, name: "get_downtime", arguments: { line_id: 1, report: "summary" }, invalid: false, error: "", duration_ms: 40 }],
    feedback: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(api, "getAssistantStatus").mockResolvedValue(STATUS);
  vi.spyOn(api, "createConversation").mockResolvedValue({
    id: 5, title: "", line: 1, line_name: "Bottling Line", context_start: null, context_end: null,
    created_at: "", updated_at: "",
  });
});

describe("the answer stream", () => {
  it("reads server-sent events split across chunks", async () => {
    const text =
      'event: progress\ndata: {"tool": "get_oee", "label": "Checking the OEE…"}\n\n' +
      'event: delta\ndata: {"text": "OEE was "}\n\nevent: delta\ndata: {"text": "78.4%."}\n\n' +
      `event: final\ndata: ${JSON.stringify(answer())}\n\n`;
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < text.length; i += 17) controller.enqueue(encoder.encode(text.slice(i, i + 17)));
        controller.close();
      },
    });
    vi.spyOn(client, "apiStream").mockResolvedValue(new Response(body));
    const events: StreamEvent[] = [];
    await askQuestion(5, "OEE?", (e) => events.push(e));
    expect(events.map((e) => e.type)).toEqual(["progress", "delta", "delta", "final"]);
    expect(events[1]).toEqual({ type: "delta", text: "OEE was " });
  });

  it("shows progress steps and text while streaming, then the stored answer", async () => {
    let finish: () => void = () => {};
    vi.spyOn(api, "askQuestion").mockImplementation(async (_id, _q, onEvent) => {
      onEvent({ type: "progress", tool: "get_downtime", label: "Checking the downtime…" });
      onEvent({ type: "delta", text: "The line lost " });
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const getConversation = vi.spyOn(api, "getConversation").mockResolvedValue({
      id: 5, title: "Downtime?", line: 1, line_name: "Bottling Line", context_start: null, context_end: null,
      created_at: "", updated_at: "",
      messages: [{ ...answer(), id: 41, role: "user", content: "Downtime?" }, answer()],
    });
    const created: number[] = [];
    function Harness() {
      const [id, setId] = useState<number | null>(null);
      return (
        <AssistantChat
          conversationId={id}
          onConversation={(next) => {
            created.push(next);
            setId(next);
          }}
        />
      );
    }
    renderWithProviders(<Harness />);

    fireEvent.change(await screen.findByLabelText("Your question"), { target: { value: "Downtime?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    const stream = await screen.findByTestId("streaming");
    expect(within(stream).getByText("Checking the downtime…")).toBeInTheDocument();
    expect(within(stream).getByText("The line lost")).toBeInTheDocument();
    expect(created).toEqual([5]);

    act(() => finish());
    expect(await screen.findByTestId("answer")).toBeInTheDocument();
    expect(screen.queryByTestId("streaming")).toBeNull();
    expect(getConversation).toHaveBeenCalledWith(5);
  });
});

describe("AnswerCard", () => {
  it("links each source chip to its screen", () => {
    renderWithProviders(<AnswerCard answer={answer()} conversationId={5} />);
    expect(screen.getByTestId("source-1")).toHaveAttribute("href", "/lines/1/downtime?start=2026-10-12T10%3A00%3A00Z");
    expect(screen.getByTestId("source-2")).toHaveAttribute("href", "/lines/1/downtime?incident=14");
    expect(screen.getByTestId("source-3")).toHaveAttribute("href", "/maintenance/7");
    expect(screen.getByTestId("answer-range")).toHaveTextContent("Mon 12 Oct 2026 10:00–10:15 (UTC)");
    expect(screen.getByTestId("answer-metrics")).toHaveTextContent("12.5 min");
  });

  it("marks unverified numbers and numbers from the question with words, not colour alone", () => {
    const { container } = renderWithProviders(<AnswerCard answer={answer()} conversationId={5} />);
    const unverified = container.querySelector('[data-number="unverified"]');
    expect(unverified).toHaveTextContent("99(not verified)");
    expect(unverified?.querySelector("svg")).not.toBeNull();
    expect(container.querySelector('[data-number="from_question"]')).toHaveTextContent("85(from your question)");
    expect(container.querySelectorAll("[data-number]")).toHaveLength(2); // 12.5 is verified: plain
    expect(screen.getByTestId("number-check")).toHaveTextContent("1 not verified");
  });

  it("shows the tools it used under “How I got this”", () => {
    renderWithProviders(<AnswerCard answer={answer()} conversationId={5} />);
    const toggle = screen.getByRole("button", { name: "How I got this (1 steps)" });
    expect(screen.queryByTestId("how-i-got-this")).toBeNull();
    fireEvent.click(toggle);
    const trace = screen.getByTestId("how-i-got-this");
    expect(trace).toHaveTextContent("Checking the downtime…");
    expect(trace).toHaveTextContent('"report": "summary"');
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("sends feedback", async () => {
    const send = vi.spyOn(api, "sendFeedback").mockResolvedValue(answer({ feedback: { helpful: true, comment: "" } }));
    renderWithProviders(<AnswerCard answer={answer()} conversationId={5} />);
    fireEvent.click(screen.getByRole("button", { name: "Helpful" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith(42, true));
    expect(await screen.findByText("Thanks for your feedback.")).toBeInTheDocument();
  });
});

describe("unavailable states", () => {
  const chat = () => renderWithProviders(<AssistantChat conversationId={null} onConversation={() => {}} />);

  it("assistant disabled", async () => {
    vi.spyOn(api, "getAssistantStatus").mockResolvedValue({ ...STATUS, enabled: false });
    chat();
    expect(await screen.findByTestId("unavailable-disabled")).toHaveTextContent("The assistant is turned off");
    expect(screen.queryByLabelText("Your question")).toBeNull();
  });

  it("model unreachable", async () => {
    vi.spyOn(api, "getAssistantStatus").mockResolvedValue({ ...STATUS, reachable: false, error: "Cannot connect" });
    chat();
    expect(await screen.findByTestId("unavailable-unreachable")).toHaveTextContent("Model unreachable");
    expect(screen.getByLabelText("Your question")).toBeDisabled();
  });

  it("daily limit reached", async () => {
    vi.spyOn(api, "getAssistantStatus").mockResolvedValue({ ...STATUS, questions_today: 30 });
    chat();
    expect(await screen.findByTestId("unavailable-daily_limit")).toHaveTextContent("You have asked 30 questions today");
  });

  it("busy, with a retry", async () => {
    const ask = vi.spyOn(api, "askQuestion").mockImplementation(async (_id, _q, onEvent) => {
      onEvent({ type: "error", code: "busy", message: "The assistant is busy.", answer: null });
    });
    vi.spyOn(api, "getConversation").mockResolvedValue({
      id: 5, title: "", line: null, line_name: null, context_start: null, context_end: null, created_at: "", updated_at: "", messages: [],
    });
    chat();
    fireEvent.click(await screen.findByRole("button", { name: "Which machine caused the most downtime this week?" }));
    const busy = await screen.findByTestId("unavailable-busy");
    expect(busy).toHaveTextContent("The assistant is busy");
    fireEvent.click(within(busy).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
  });

  it("daily limit refused by the server", async () => {
    vi.spyOn(api, "askQuestion").mockRejectedValue(new ApiError(429, { code: "daily_limit", limit: 30 }));
    chat();
    fireEvent.change(await screen.findByLabelText("Your question"), { target: { value: "Again?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByTestId("unavailable-daily_limit")).toBeInTheDocument();
  });
});

describe("side panel", () => {
  it("opens pre-filled with the screen's line and range", async () => {
    const ask = vi.spyOn(api, "askQuestion").mockResolvedValue();
    vi.spyOn(api, "getConversation").mockResolvedValue({
      id: 5, title: "", line: 1, line_name: "Bottling Line", context_start: null, context_end: null, created_at: "", updated_at: "", messages: [],
    });
    renderWithProviders(
      <AskAssistantButton lineId={1} lineName="Bottling Line" start="2026-10-12T06:00:00Z" end="2026-10-12T14:00:00Z" zone="UTC" />,
    );
    fireEvent.click(screen.getByTestId("ask-assistant"));
    const panel = await screen.findByRole("dialog", { name: "Assistant" });
    expect(await within(panel).findByTestId("assistant-context")).toHaveTextContent("About Bottling Line · 06:00–14:00 (UTC)");

    fireEvent.change(within(panel).getByLabelText("Your question"), { target: { value: "Why did it stop?" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Ask" }));
    await waitFor(() =>
      expect(api.createConversation).toHaveBeenCalledWith({
        line: 1,
        context_start: "2026-10-12T06:00:00Z",
        context_end: "2026-10-12T14:00:00Z",
      }),
    );
    await waitFor(() => expect(ask).toHaveBeenCalledWith(5, "Why did it stop?", expect.any(Function)));
  });
});
