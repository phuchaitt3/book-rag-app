"use client";

import { useCallback, useEffect, useState } from "react";

import { API_URL, type Book, MAX_CHAT_BOOKS, apiHeaders, routes } from "@/api/client";

import { Chat } from "./chat";
import { UploadForm } from "./upload-form";

export function Library() {
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}${routes.books}`, { headers: apiHeaders() });
      if (!res.ok) throw new Error(`could not list books (${res.status})`);
      const list: Book[] = await res.json();
      setBooks(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading the list on mount
    void load();
  }, [load]);

  const chosen = books.filter((b) => selected.includes(b.id));

  const toggle = (id: string) =>
    setSelected((ids) =>
      ids.includes(id)
        ? ids.filter((x) => x !== id)
        : ids.length < MAX_CHAT_BOOKS
          ? [...ids, id]
          : ids,
    );

  return (
    <div className="flex flex-col gap-8">
      <UploadForm onUploaded={load} />
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Books</h2>
        <p className="text-sm text-zinc-500">
          Pick one or more (up to {MAX_CHAT_BOOKS}) to ask a question across them.
        </p>
        {error && (
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        {books.length === 0 && !error && (
          <p className="text-sm text-zinc-500">No books yet. Upload a text PDF to start.</p>
        )}
        <ul className="flex flex-col gap-1">
          {books.map((b) => (
            <li key={b.id}>
              <button
                type="button"
                onClick={() => toggle(b.id)}
                aria-pressed={selected.includes(b.id)}
                className="w-full rounded px-2 py-1 text-left hover:bg-zinc-100 aria-pressed:bg-zinc-200 dark:hover:bg-zinc-800 dark:aria-pressed:bg-zinc-700"
              >
                {b.title}
                {b.page_count != null && (
                  <span className="text-sm text-zinc-500"> · {b.page_count} pages</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </section>
      {chosen.length > 0 && <Chat key={chosen.map((b) => b.id).join(",")} books={chosen} />}
    </div>
  );
}
