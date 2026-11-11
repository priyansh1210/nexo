"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { Icon } from "@/components/icons";
import type { Account, Answer, HistoryEntry } from "@/lib/types";

import { ask } from "./actions";
import { AnswerView } from "./answer";
import { EvidencePanel, type Opened } from "./evidence-panel";

type Turn = { key: number; question: string; answer?: Answer; accounts?: Account[]; error?: string };

// The demo's story, as starting points: what a CSM asks on a Monday morning.
const STARTERS = [
  "Which customers renewing next month need attention?",
  "Investigate Acme.",
  "Is our data up to date?",
];

export function Chat({
  conversationId,
  isNew,
  history,
  prefill,
}: {
  conversationId: string;
  isNew: boolean;
  history: HistoryEntry[];
  prefill: string; // a question handed over from another screen, ready to send or change
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [opened, setOpened] = useState<Opened>();
  const [pending, startTransition] = useTransition();
  const [draft, setDraft] = useState(prefill);
  const openedBy = useRef<HTMLElement | null>(null);
  const started = useRef(!isNew);
  const turnCount = useRef(0);
  const latest = useRef<HTMLLIElement>(null);

  // A new question scrolls into view, so its answer (and any approval) appears where the eye is.
  useEffect(() => {
    if (!turns.length) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    latest.current?.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
  }, [turns.length]);

  const close = useCallback(() => {
    setOpened(undefined);
    openedBy.current?.focus();
  }, []);

  function send(question: string) {
    const text = question.trim();
    if (!text || pending) return;
    if (!started.current) {
      // Keep the conversation in the address, so a reload or a shared link comes back to it.
      window.history.replaceState(null, "", `/chat?c=${conversationId}`);
      started.current = true;
    }
    const key = ++turnCount.current;
    setDraft("");
    setTurns((all) => [...all, { key, question: text }]);
    startTransition(async () => {
      const result = await ask(conversationId, text);
      setTurns((all) => all.map((turn) => (turn.key === key ? { ...turn, ...result } : turn)));
    });
  }

  const empty = !history.length && !turns.length;
  return (
    <div className="grid gap-8 min-[1100px]:grid-cols-[minmax(0,720px)_minmax(300px,1fr)]">
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-4">
          <h1 className="text-[22px] font-semibold">Chat</h1>
          {!empty && (
            <Link href="/chat" className="link text-sm">
              New conversation
            </Link>
          )}
        </div>

        {empty && (
          <div className="mt-6">
            <p className="text-ink-2">
              Ask about your accounts. Every answer cites the data it used and says how fresh it is. Actions the
              assistant drafts wait for your approval.
            </p>
            <ul className="mt-5 space-y-2" aria-label="Suggested questions">
              {STARTERS.map((starter) => (
                <li key={starter}>
                  <button type="button" className="link text-left" onClick={() => send(starter)}>
                    {starter}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {history.length > 0 && (
          <section aria-label="Earlier in this conversation" className="mt-6 space-y-4 text-sm">
            <p className="label">Earlier in this conversation</p>
            {history.map((entry, index) => (
              <div key={index} className="border-l border-rule pl-4">
                <p className="font-medium">{entry.question}</p>
                <p className="mt-0.5 text-ink-2">{entry.summary}</p>
              </div>
            ))}
            <p className="text-[13px] text-ink-2">Sources are shown for answers from this visit; ask again to see them.</p>
          </section>
        )}

        <ol className="mt-6 space-y-10" aria-live="polite">
          {turns.map((turn, index) => (
            <li
              key={turn.key}
              ref={index === turns.length - 1 ? latest : undefined}
              className="scroll-mt-6 space-y-4"
            >
              <p className="border-l-2 border-accent pl-3 font-medium">{turn.question}</p>
              {turn.answer ? (
                <AnswerView
                  answer={turn.answer}
                  accounts={turn.accounts ?? []}
                  openSource={(callId, chip) => {
                    openedBy.current = chip;
                    setOpened({ answer: turn.answer!, callId });
                  }}
                />
              ) : turn.error ? (
                <p role="alert" className="flex items-start gap-2 text-sm text-failed">
                  <Icon name="warning" className="mt-0.5 size-4 shrink-0" />
                  <span>
                    The question could not be answered: {turn.error}{" "}
                    <button type="button" className="link" onClick={() => send(turn.question)}>
                      Ask again
                    </button>
                  </span>
                </p>
              ) : (
                <p className="text-sm text-ink-2">Checking the data…</p>
              )}
            </li>
          ))}
        </ol>

        <form
          className="sticky bottom-0 mt-8 bg-paper pb-4 pt-2"
          onSubmit={(event) => {
            event.preventDefault();
            send(draft);
          }}
        >
          <label htmlFor="question" className="sr-only">
            Ask about an account
          </label>
          <div className="flex items-end gap-2 rounded-md border border-rule bg-surface p-2 focus-within:border-accent">
            <textarea
              id="question"
              rows={1}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send(draft);
                }
              }}
              placeholder="Ask about an account, a renewal, or your data"
              maxLength={2000}
              autoFocus={Boolean(prefill)}
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[15px] outline-none field-sizing-content"
            />
            <button
              type="submit"
              className="button button-primary px-2.5"
              disabled={pending || !draft.trim()}
              aria-label="Send"
            >
              <Icon name="send" className="size-5" />
            </button>
          </div>
          <p className="mt-1.5 text-[12px] text-ink-2">Enter sends · Shift+Enter adds a line</p>
        </form>
      </div>

      <div className="min-w-0">
        {opened ? (
          <EvidencePanel opened={opened} onClose={close} />
        ) : (
          <p className="hidden text-sm text-ink-2 min-[1100px]:block min-[1100px]:pt-12">
            Select a source number, like [1], to see the data behind a statement.
          </p>
        )}
      </div>
    </div>
  );
}
