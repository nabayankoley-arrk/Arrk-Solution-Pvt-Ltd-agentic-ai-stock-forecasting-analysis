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
}

// Mirrors backend/main.py's ChatResponse (the POST /api/chat response body)
// field for field, including the snake_case key FastAPI actually returns.
export interface ChatApiResponse {
  reply: string;
  response_type: "analysis" | "reply" | "out_of_scope" | "error";
  session_id: string;
  ticker?: string | null;
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
