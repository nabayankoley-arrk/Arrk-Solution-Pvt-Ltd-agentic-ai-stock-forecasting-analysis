// Shared chat types and helpers for the page and its components.
//
// This module was referenced (three imports: page.tsx, MessageBubble.tsx,
// Sidebar.tsx) but never committed, so `next build` failed with
// "Module not found: Can't resolve './lib/chat'" before this file existed.
// The shape below is reconstructed from those three call sites and from
// backend/main.py's ChatResponse model (POST /api/chat), not from any
// separate spec -- there is nothing else to cross-check it against.

export type ChatRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  // Only ever set on an "assistant" message built from a ChatApiResponse.
  responseType?: ChatApiResponse["response_type"];
  ticker?: string | null;
  // Set while an assistant reply is still streaming in (see streamChat).
  streaming?: boolean;
  status?: string; // e.g. "Analysing TCS.NS..." -- shown until the first token arrives
}

// Mirrors backend/main.py's ChatResponse (the POST /api/chat response body)
// field for field, including the snake_case key FastAPI actually returns.
export interface ChatApiResponse {
  reply: string;
  response_type: "analysis" | "reply" | "error";
  session_id: string;
  ticker?: string | null;
}

export interface ChatRequestBody {
  message: string;
  user_id: string;
  session_id?: string;
}

export interface StreamHandlers {
  onStatus: (message: string) => void;
  onToken: (text: string) => void;
}

// POST /api/chat/stream, read as Server-Sent Events (backend/main.py's
// run_chat_stream): `status` while an analysis runs, `token` pieces of the
// reply, then always `done` with the same body POST /api/chat returns --
// resolved here, and authoritative over the tokens. fetch + a stream reader
// rather than EventSource, which only supports GET.
export async function streamChat(body: ChatRequestBody, handlers: StreamHandlers): Promise<ChatApiResponse> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(`Request failed (${response.status}): ${await response.text()}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const payload = JSON.parse(data);

      if (event === "status") handlers.onStatus(payload.message);
      else if (event === "token") handlers.onToken(payload.text);
      else if (event === "done") return payload as ChatApiResponse;
    }
  }
  throw new Error("The response ended before the reply was complete.");
}

// crypto.randomUUID() is available in every evergreen browser and in the
// Node version `next build`'s static export prerenders under, but this
// falls back rather than assuming it, since it is invoked at module-eval
// time (page.tsx's initial useState) rather than behind a user action.
export function uid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// A stable per-browser id, sent as /api/chat's user_id so the backend's audit
// log can group one browser's conversations. Falls back to a fresh id per page
// load when localStorage is unavailable (private mode, blocked storage).
const USER_ID_KEY = "stock-chat-user-id";

export function getUserId(): string {
  try {
    const existing = localStorage.getItem(USER_ID_KEY);
    if (existing) return existing;
    const created = uid();
    localStorage.setItem(USER_ID_KEY, created);
    return created;
  } catch {
    return uid();
  }
}

// The one message a fresh chat (initial load, or "New session") opens with.
// Role "assistant" (not "system"): MessageBubble renders "system" as a small
// centered pill meant for transient notices like a network error, not as the
// first thing a caller reads in an empty conversation.
export function newSessionMessage(): ChatMessage {
  return {
    id: uid(),
    role: "assistant",
    content:
      'Hi! Ask about any tracked stock -- e.g. "how is TCS.NS looking today?" -- ' +
      "and I'll pull together technical, fundamental, and sentiment signals.",
  };
}

// Sidebar's "Try asking" shortcuts. The backend's LLM resolves company names
// and follow-ups from the conversation, so plain phrasing works.
export const EXAMPLE_PROMPTS: string[] = [
  "How is TCS.NS looking today?",
  "What's the trend for INFY.NS?",
  "Is RELIANCE.NS a buy right now?",
  "What is the latest forecast?",
];
