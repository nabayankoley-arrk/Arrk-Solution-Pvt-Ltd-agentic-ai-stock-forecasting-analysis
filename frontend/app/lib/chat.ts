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
  response_type: "analysis" | "out_of_scope" | "error";
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

// Sidebar's "Try asking" shortcuts. NSE-suffixed tickers and a keyword-only
// follow-up, matching what the backend's parse_and_route.py actually resolves
// (an explicit ticker, or one of config.STOCK_KEYWORDS against the watchlist
// memory already established -- a follow-up with neither is routed
// out_of_scope, so no example here is phrased that way).
export const EXAMPLE_PROMPTS: string[] = [
  "How is TCS.NS looking today?",
  "What's the trend for INFY.NS?",
  "Is RELIANCE.NS a buy right now?",
  "What is the latest forecast?",
];
