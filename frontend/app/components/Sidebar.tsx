import { LineChart, Plus, X } from "lucide-react";
import { EXAMPLE_PROMPTS } from "../lib/chat";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  sessionId: string | null;
  tickers: string[];
  onNewSession: () => void;
  onPromptClick: (prompt: string) => void;
}

export default function Sidebar({
  open,
  onClose,
  sessionId,
  tickers,
  onNewSession,
  onPromptClick,
}: SidebarProps) {
  return (
    <>
      {open ? (
        <div
          onClick={onClose}
          className="fixed inset-0 z-20 bg-slate-950/40 md:hidden"
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={
          "fixed inset-y-0 left-0 z-30 flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white transition-transform duration-200 dark:border-slate-800 dark:bg-slate-900 md:static md:translate-x-0 " +
          (open ? "translate-x-0" : "-translate-x-full")
        }
      >
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-4 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white">
              <LineChart className="h-4.5 w-4.5" />
            </div>
            <div>
              <p className="text-sm font-semibold leading-tight text-slate-900 dark:text-slate-100">
                Agentic Stock AI
              </p>
              <p className="text-[11px] leading-tight text-slate-400">Analysis assistant</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 md:hidden"
            aria-label="Close sidebar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4">
          <button
            type="button"
            onClick={onNewSession}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:text-indigo-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-indigo-500 dark:hover:text-indigo-400"
          >
            <Plus className="h-4 w-4" />
            New session
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 pb-4">
          <section className="mb-6">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Session
            </h2>
            <code className="block break-all rounded-lg bg-slate-100 px-2.5 py-2 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {sessionId ?? "(not started)"}
            </code>
          </section>

          <section className="mb-6">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Tickers discussed
            </h2>
            {tickers.length === 0 ? (
              <p className="text-xs text-slate-400">None yet this session.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tickers.map((t) => (
                  <span
                    key={t}
                    className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Try asking
            </h2>
            <div className="flex flex-col gap-1.5">
              {EXAMPLE_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => onPromptClick(prompt)}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-left text-xs text-slate-600 transition hover:border-indigo-300 hover:bg-indigo-50/60 hover:text-indigo-700 dark:border-slate-800 dark:text-slate-400 dark:hover:border-indigo-500/40 dark:hover:bg-indigo-500/5 dark:hover:text-indigo-400"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </section>
        </div>
      </aside>
    </>
  );
}
