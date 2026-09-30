import { Bot, ChevronRight, Newspaper, User } from "lucide-react";
import type { ChatMessage, ClarificationOption, NewsItem } from "../lib/chat";

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

function renderInline(text: string) {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, partIndex) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={partIndex} className="font-semibold text-slate-900 dark:text-white">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

// The reply's layout (backend agent prompt): a bold line on its own is a
// section label, "- " lines are bullets, blank lines separate sections, and
// **bold** inside a line is kept. "# Heading" lines, which some models still
// write, are shown as section labels too.
const SECTION_LABEL = /^(#{1,6}\s+.*|\*\*[^*]+\*\*[^*]*)$/;

function renderText(content: string) {
  const lines = content.split("\n");
  return lines.map((line, lineIndex) => {
    const heading = /^#{1,6}\s+(.*)$/.exec(line.trim());
    const label = heading ? heading[1] : /^\*\*([^*]+)\*\*(.*)$/.exec(line.trim());
    if (!line.trim()) {
      // A blank line right after a section label would split it from its lines.
      const previous = (lines[lineIndex - 1] ?? "").trim();
      if (lineIndex > 0 && SECTION_LABEL.test(previous) && lineIndex - 1 > 0) return null;
      return <div key={lineIndex} className="h-2" aria-hidden />;
    }
    if (typeof label === "string" || (label && !/\*\*/.test(label[2]))) {
      const [title, rest] = typeof label === "string" ? [label, ""] : [label[1], label[2]];
      return (
        <div key={lineIndex} className={lineIndex === 0 ? "pb-0.5 text-[0.98rem]" : "pt-0.5"}>
          <span className="font-semibold text-slate-900 dark:text-white">{title}</span>
          {rest ? <span className="text-slate-500 dark:text-slate-400">{rest}</span> : null}
        </div>
      );
    }
    const bullet = /^\s*[-•]\s+(.*)$/.exec(line);
    if (bullet) {
      return (
        <div key={lineIndex} className="flex gap-2 pl-1">
          <span className="select-none text-slate-400" aria-hidden>
            •
          </span>
          <span className="min-w-0">{renderInline(bullet[1])}</span>
        </div>
      );
    }
    return <div key={lineIndex}>{renderInline(line)}</div>;
  });
}

const NEWS_LABEL_STYLES: Record<string, string> = {
  bullish: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  bearish: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-400",
};

// The turn's news sources (searched live by the backend): the reply already
// tells the stories, so each company is one collapsed line -- its news
// sentiment and article count -- that opens to the linked articles.
function NewsList({ news }: { news: NewsItem[] }) {
  return (
    <div className="flex w-full flex-col divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white text-sm shadow-sm dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
      {news.map((item, itemIndex) => (
        <details key={item.ticker ?? item.company ?? itemIndex} className="group px-4 py-2.5">
          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 [&::-webkit-details-marker]:hidden">
            <ChevronRight className="h-3.5 w-3.5 text-slate-400 transition-transform group-open:rotate-90" />
            <Newspaper className="h-3.5 w-3.5 text-slate-400" />
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
              News sources{item.ticker || item.company ? ` · ${item.ticker ?? item.company}` : ""}
            </span>
            <span className="text-[11px] text-slate-400 dark:text-slate-500">
              {item.articles.length} article{item.articles.length === 1 ? "" : "s"}
            </span>
            {item.label ? (
              <span
                className={
                  "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium " +
                  (NEWS_LABEL_STYLES[item.label] ?? NEWS_LABEL_STYLES.neutral)
                }
              >
                {item.label}
              </span>
            ) : null}
          </summary>
          <ul className="mt-2 flex flex-col gap-2 pl-5">
            {item.articles.map((article, articleIndex) => (
              <li key={article.url ?? articleIndex} className="leading-snug">
                {article.url ? (
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-700 hover:underline dark:text-indigo-300"
                  >
                    {article.title}
                  </a>
                ) : (
                  <span className="text-slate-800 dark:text-slate-100">{article.title}</span>
                )}
                <span className="ml-1.5 text-[11px] text-slate-400 dark:text-slate-500">
                  {[article.source, article.published].filter(Boolean).join(" · ")}
                </span>
                {article.summary ? (
                  <p className="mt-0.5 text-[13px] leading-snug text-slate-600 dark:text-slate-300">
                    {article.summary}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          <p className="mt-2 pl-5 text-[11px] italic text-slate-400 dark:text-slate-500">
            Third-party news, fetched when you asked. Not this app&apos;s analysis.
          </p>
        </details>
      ))}
    </div>
  );
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
        {message.news?.length ? <NewsList news={message.news} /> : null}
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
