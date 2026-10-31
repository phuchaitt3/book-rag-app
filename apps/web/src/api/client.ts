import type { components, paths } from "./schema";

// The types in ./schema.d.ts are generated from the API's OpenAPI document (ADR 0007).
// After an API change, run `pnpm gen:api` from the repository root.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Route paths as the API declares them. `satisfies keyof paths` makes a route the API no longer
// has fail to compile; the two with a parameter are filled in by the helpers below.
export const routes = {
  healthz: "/healthz",
  readyz: "/readyz",
  books: "/books",
  ingestionJob: "/ingestion-jobs/{job_id}",
  chat: "/books/{book_id}/chat",
} as const satisfies Record<string, keyof paths>;

export const ingestionJobPath = (jobId: string) =>
  routes.ingestionJob.replace("{job_id}", encodeURIComponent(jobId));
export const chatPath = (bookId: string) =>
  routes.chat.replace("{book_id}", encodeURIComponent(bookId));

type Schemas = components["schemas"];

export type Book = Schemas["BookOut"];
export type UploadedBook = Schemas["UploadedBook"];
export type IngestionProgress = Schemas["IngestionProgress"];
export type ChatRequest = Schemas["ChatRequest"];
export type Citation = Schemas["Citation"];

// The chat answer is a stream of server-sent events: `citations` once, then many `token`,
// then `done`, or `error` if the model fails part-way.
export type ChatEvent =
  | { event: "citations"; data: Citation[] }
  | { event: "token"; data: Schemas["TokenEvent"] }
  | { event: "done"; data: Schemas["DoneEvent"] }
  | { event: "error"; data: Schemas["ErrorEvent"] };
