"use client";

import { Menu, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import MessageBubble from "./components/MessageBubble";
import Sidebar from "./components/Sidebar";
import {
  ChatApiResponse,
  ChatMessage,
  ChatRequestBody,
  getUserId,
  newSessionMessage,
  streamChat,
  uid,
} from "./lib/chat";

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([newSessionMessage()]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  function addMessage(msg: Omit<ChatMessage, "id">) {
    setMessages((prev) => [...prev, { ...msg, id: uid() }]);
  }

  function resetSession() {
    setSessionId(null);
    setTickers([]);
    setMessages([newSessionMessage()]);
    setSidebarOpen(false);
  }

  function fillPrompt(prompt: string) {
    setInput(prompt);
    setSidebarOpen(false);
    inputRef.current?.focus();
  }

  async function sendMessage(message: string) {
    if (!message || loading) return;

    addMessage({ role: "user", content: message });
    setInput("");
    setLoading(true);

    // The assistant's bubble exists from the start and fills in as the reply streams.
    const replyId = uid();
    setMessages((prev) => [...prev, { id: replyId, role: "assistant", content: "", streaming: true }]);

    try {
      const body: ChatRequestBody = { message, user_id: getUserId() };
      if (sessionId) body.session_id = sessionId;

      const data: ChatApiResponse = await streamChat(body, {
        onStatus: (status) => updateMessage(replyId, (m) => ({ ...m, status })),
        onToken: (text) => updateMessage(replyId, (m) => ({ ...m, content: m.content + text, status: undefined })),
      });

      setSessionId(data.session_id);
      if (data.ticker) {
        setTickers((prev) => (prev.includes(data.ticker as string) ? prev : [...prev, data.ticker as string]));
      }
      updateMessage(replyId, (m) => ({
        ...m,
        content: data.reply,
        responseType: data.response_type,
        ticker: data.ticker,
        streaming: false,
        status: undefined,
      }));
    } catch (err) {
      updateMessage(replyId, () => ({ id: replyId, role: "system", content: String(err instanceof Error ? err.message : err) }));
    } finally {
      setLoading(false);
    }
  }

  function updateMessage(id: string, update: (message: ChatMessage) => ChatMessage) {
    setMessages((prev) => prev.map((m) => (m.id === id ? update(m) : m)));
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    void sendMessage(input.trim());
  }

  return (
    <div className="flex h-dvh bg-slate-50 dark:bg-slate-950">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessionId={sessionId}
        tickers={tickers}
        onNewSession={resetSession}
        onPromptClick={fillPrompt}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80 md:px-6">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 md:hidden"
            aria-label="Open sidebar"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div>
            <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Agentic AI Stock Analysis
            </h1>
            <p className="hidden text-xs text-slate-400 sm:block">
              Ask about a tracked ticker, e.g. &ldquo;how is INFY.NS looking?&rdquo;
            </p>
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-5 md:px-8">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </div>
        </div>

        <div className="border-t border-slate-200 bg-white/80 px-4 py-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80 md:px-8">
          <form onSubmit={handleSubmit} autoComplete="off" className="mx-auto flex max-w-3xl gap-2">
            <input
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              disabled={loading}
              autoFocus
              placeholder="Ask about a stock&hellip;"
              className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-indigo-500/20"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="flex items-center justify-center rounded-xl bg-indigo-600 px-4 text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Send message"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
