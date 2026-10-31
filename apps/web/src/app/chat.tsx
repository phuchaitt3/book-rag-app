"use client";

import { useRef, useState } from "react";

import { API_URL, type Book, type Citation, chatPath } from "@/api/client";
import { readEvents } from "@/api/stream";

type Turn = { question: string; answer: string; citations: Citation[]; error?: string };

export function Chat({ book }: { book: Book }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const update = (patch: (turn: Turn) => Turn) =>
    setTurns((all) => [...all.slice(0, -1), patch(all[all.length - 1])]);

  async function ask(form: FormData) {
    const question = String(form.get("question") ?? "").trim();
    if (!question) return;
    setTurns((all) => [...all, { question, answer: "", citations: [] }]);
    setBusy(true);
    abort.current = new AbortController();
    try {
      const res = await fetch(`${API_URL}${chatPath(book.id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: abort.current.signal,
      });
      if (!res.ok || !res.body) throw new Error(`request failed (${res.status})`);
      for await (const event of readEvents(res.body)) {
        if (event.event === "citations") update((t) => ({ ...t, citations: event.data }));
        else if (event.event === "token")
          update((t) => ({ ...t, answer: t.answer + event.data.text }));
        else if (event.event === "error") update((t) => ({ ...t, error: event.data.message }));
      }
    } catch (e) {
      if (!abort.current.signal.aborted)
        update((t) => ({ ...t, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-medium">Ask about “{book.title}”</h2>
      {turns.map((turn, i) => (
        <article key={i} className="flex flex-col gap-2">
          <p className="font-medium">{turn.question}</p>
          <p className="whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">
            {turn.answer || (busy && i === turns.length - 1 ? "…" : "")}
          </p>
          {turn.error && (
            <p className="text-sm text-red-600" role="alert">
              {turn.error}
            </p>
          )}
          {turn.citations.length > 0 && <CitationChips citations={turn.citations} />}
        </article>
      ))}
      <form action={ask} className="flex gap-2">
        <input
          name="question"
          required
          maxLength={2000}
          placeholder="Ask a question"
          className="flex-1 rounded border border-zinc-300 px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-900"
        />
        {busy ? (
          <button
            type="button"
            onClick={() => abort.current?.abort()}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900"
          >
            Ask
          </button>
        )}
      </form>
    </section>
  );
}

function CitationChips({ citations }: { citations: Citation[] }) {
  return (
    <ul className="flex flex-wrap gap-2 text-xs">
      {citations.map((c) => (
        <li
          key={c.chunk_id}
          title={c.section ?? undefined}
          className="rounded-full bg-zinc-100 px-2.5 py-1 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
        >
          [{c.number}] {c.book_title}
          {c.section && ` · ${c.section}`}
          {c.page != null && ` · p. ${c.page}`}
        </li>
      ))}
    </ul>
  );
}
