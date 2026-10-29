import { ApiStatus } from "./api-status";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-24">
      <h1 className="text-3xl font-semibold tracking-tight">Book RAG</h1>
      <p className="text-lg text-zinc-600 dark:text-zinc-400">
        Ask questions about Vietnamese books and get answers with citations to the section and
        page.
      </p>
      <ApiStatus />
    </main>
  );
}
