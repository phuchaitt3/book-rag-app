import type { components, paths } from "./schema";

// The types in ./schema.d.ts are generated from the API's OpenAPI document (ADR 0007).
// After an API change, run `pnpm gen:api` from the repository root.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Who the API thinks is calling (#230). Until a real login exists (ADR 0006) the API reads this
// header, and only when it runs with ENVIRONMENT=development or test; elsewhere it answers 401.
// The default is the owner of every book that existed before owners did.
export const DEV_USER = process.env.NEXT_PUBLIC_DEV_USER ?? "dev-user";
export const DEV_USER_HEADER = "X-Dev-User";

/** Headers every API call carries; pass extra ones (a Content-Type) in `extra`. */
export const apiHeaders = (extra: Record<string, string> = {}): Record<string, string> => ({
  [DEV_USER_HEADER]: DEV_USER,
  ...extra,
});

// Route paths as the API declares them. `satisfies keyof paths` makes a route the API no longer
// has fail to compile; the one with a parameter is filled in by the helper below.
export const routes = {
  healthz: "/healthz",
  readyz: "/readyz",
  books: "/books",
  ingestionJob: "/ingestion-jobs/{job_id}",
  chat: "/chat",
} as const satisfies Record<string, keyof paths>;

export const ingestionJobPath = (jobId: string) =>
  routes.ingestionJob.replace("{job_id}", encodeURIComponent(jobId));

type Schemas = components["schemas"];

export type Book = Schemas["BookOut"];
export type UploadedBook = Schemas["UploadedBook"];
export type IngestionProgress = Schemas["IngestionProgress"];
export type ChatRequest = Schemas["MultiChatRequest"];
// POST /chat accepts 1 to 10 books (docs/design/multi-book-chat.md).
export const MAX_CHAT_BOOKS = 10;
export type Citation = Schemas["Citation"];

// The chat answer is a stream of server-sent events: `citations` once, then many `token`,
// then `done`, or `error` if the model fails part-way.
export type ChatEvent =
  | { event: "citations"; data: Citation[] }
  | { event: "token"; data: Schemas["TokenEvent"] }
  | { event: "done"; data: Schemas["DoneEvent"] }
  | { event: "error"; data: Schemas["ErrorEvent"] };
