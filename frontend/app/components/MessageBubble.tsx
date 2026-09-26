import { Bot, User } from "lucide-react";
import type { ChatMessage, ClarificationOption } from "../lib/chat";

const BADGE_STYLES: Record<string, string> = {
  analysis:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  reply: "bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400",
  clarification: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400",
  out_of_scope: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  error: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-400",
};

const BADGE_LABEL: Record<string, string> = {
  analysis: "analysis",
  reply: "reply",
  clarification: "question",
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

// The model is asked for plain text but free models still write some markdown:
// render **bold**, and show "# Heading" lines as bold text. Everything else is
// left as typed (the bubble keeps line breaks and "- " list lines as they are).
function renderText(content: string) {
  return content.split("\n").map((line, lineIndex, lines) => {
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    const text = heading ? `**${heading[1]}**` : line;
    const parts = text.split(/(\*\*[^*\n]+\*\*)/g).map((part, partIndex) =>
      part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
        <strong key={partIndex}>{part.slice(2, -2)}</strong>
      ) : (
        part
      ),
    );
    return (
      <span key={lineIndex}>
        {parts}
        {lineIndex < lines.length - 1 ? "\n" : null}
      </span>
    );
  });
}

// Before the first token: bouncing dots, plus the backend's progress status
// ("Analysing TCS.NS...") while an analysis runs.
function TypingIndicator({ status }: { status?: string }) {
  return (
    <span className="flex items-center gap-2" role="status" aria-live="polite">
      <span className="flex items-center gap-1 py-1.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
      </span>
      {status ? (
        <span className="text-xs italic text-slate-500 dark:text-slate-400">{status}</span>
      ) : (
        <span className="sr-only">Assistant is typing</span>
      )}
    </span>
  );
}

// onOption is set only while this message's clarification is still open.
export default function MessageBubble({
  message,
  onOption,
}: {
  message: ChatMessage;
  onOption?: (option: ClarificationOption) => void;
}) {
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
          {message.streaming && !message.content ? (
            <TypingIndicator status={message.status} />
          ) : (
            <>
              {isUser ? message.content : renderText(message.content)}
              {message.streaming ? (
                <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-slate-400" />
              ) : null}
            </>
          )}
        </div>
        {message.options?.length ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {message.options.map((option) => (
              <button
                key={option.ticker}
                type="button"
                onClick={() => onOption?.(option)}
                disabled={!onOption}
                className={
                  "rounded-full border px-3 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50 " +
                  (option.tracked
                    ? "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300"
                    : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400")
                }
                title={option.tracked ? undefined : "Listed, but not tracked here, so it can't be analysed"}
              >
                {option.name}
                {option.tracked ? null : <span className="ml-1 opacity-70">(not tracked)</span>}
              </button>
            ))}
          </div>
        ) : null}
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
