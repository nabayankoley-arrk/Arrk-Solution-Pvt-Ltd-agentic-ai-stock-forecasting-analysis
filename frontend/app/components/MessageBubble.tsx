import { Bot, User } from "lucide-react";
import type { ChatMessage } from "../lib/chat";

const BADGE_STYLES: Record<string, string> = {
  analysis:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  reply: "bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400",
  out_of_scope: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  error: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-400",
};

const BADGE_LABEL: Record<string, string> = {
  analysis: "analysis",
  reply: "reply",
  out_of_scope: "out of scope",
  error: "error",
};

function ResponseBadge({ responseType }: { responseType: string }) {
  return (
    <span
      className={
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium " +
        (BADGE_STYLES[responseType] ?? BADGE_STYLES.out_of_scope)
      }
    >
      {BADGE_LABEL[responseType] ?? responseType}
    </span>
  );
}

export default function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "system") {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs italic text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
          {message.content}
        </span>
      </div>
    );
  }

  const isUser = message.role === "user";

  return (
    <div className={"flex items-start gap-2.5 " + (isUser ? "flex-row-reverse" : "")}>
      <div
        className={
          "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full " +
          (isUser
            ? "bg-indigo-600 text-white"
            : "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900")
        }
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>

      <div className={"flex max-w-[78%] flex-col gap-1 " + (isUser ? "items-end" : "items-start")}>
        <div
          className={
            "whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-[0.9rem] leading-relaxed shadow-sm " +
            (isUser
              ? "rounded-tr-sm bg-indigo-600 text-white"
              : "rounded-tl-sm border border-slate-200 bg-white text-slate-800 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100")
          }
        >
          {message.content}
        </div>
        {message.responseType || message.ticker ? (
          <div className="flex items-center gap-1.5 px-1">
            {message.responseType ? <ResponseBadge responseType={message.responseType} /> : null}
            {message.ticker ? (
              <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
                {message.ticker}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
