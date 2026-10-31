"use client";

import { useCallback, useEffect, useState } from "react";

import { API_URL, type Book, routes } from "@/api/client";

import { Chat } from "./chat";
import { UploadForm } from "./upload-form";

export function Library() {
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}${routes.books}`);
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

  const book = books.find((b) => b.id === selected);

  return (
    <div className="flex flex-col gap-8">
      <UploadForm onUploaded={load} />
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-medium">Books</h2>
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
                onClick={() => setSelected(b.id)}
                aria-pressed={b.id === selected}
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
      {book && <Chat key={book.id} book={book} />}
    </div>
  );
}
