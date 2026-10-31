"use client";

import { useEffect, useState } from "react";

import {
  API_URL,
  type IngestionProgress,
  type UploadedBook,
  ingestionJobPath,
  routes,
} from "@/api/client";

const POLL_MS = 2_000;

async function errorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `request failed (${res.status})`;
}

export function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState<IngestionProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  async function submit(form: FormData) {
    setError(null);
    setProgress(null);
    setSending(true);
    try {
      const res = await fetch(`${API_URL}${routes.books}`, { method: "POST", body: form });
      if (!res.ok) throw new Error(await errorText(res));
      const uploaded: UploadedBook = await res.json();
      setJobId(uploaded.job_id);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}${ingestionJobPath(jobId)}`);
        if (!res.ok) throw new Error(await errorText(res));
        const job: IngestionProgress = await res.json();
        if (stopped) return;
        setProgress(job);
        if (job.status === "succeeded" || job.status === "failed") return;
      } catch (e) {
        if (!stopped) setError(e instanceof Error ? e.message : String(e));
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-medium">Upload a book</h2>
      <form action={submit} className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          name="file"
          accept="application/pdf"
          required
          className="text-sm file:mr-2 file:rounded file:border-0 file:bg-zinc-200 file:px-3 file:py-1.5 dark:file:bg-zinc-800"
        />
        <input
          name="title"
          placeholder="Title (optional)"
          className="rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={sending}
          className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {sending ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
      {progress && <JobProgress job={progress} />}
    </section>
  );
}

function JobProgress({ job }: { job: IngestionProgress }) {
  const percent =
    job.chunks_total > 0 ? Math.round((100 * job.chunks_embedded) / job.chunks_total) : 0;
  const label =
    job.status === "running"
      ? `${job.stage ?? "working"}: ${job.chunks_embedded}/${job.chunks_total} chunks embedded`
      : job.status === "failed"
        ? `failed: ${job.error ?? "unknown error"}`
        : job.status;
  return (
    <div className="flex flex-col gap-1 text-sm" role="status">
      <span>Ingestion {label}</span>
      <progress value={job.status === "succeeded" ? 100 : percent} max={100} className="w-full" />
    </div>
  );
}
