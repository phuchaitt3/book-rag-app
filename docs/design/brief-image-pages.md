# Brief: reading scanned and image-only PDF pages

**Needed for:** [#268](https://github.com/phuchaitt3/book-rag-app/issues/268)   **Status:** draft

Nothing here is measured yet. Every number below is either a count taken from the code or a target fixed in advance; each is labelled. The measurement plan says how the real figures will be produced.

## Problem

The parser reads the PDF text layer only. [`parse_pdf`](../../packages/rag/src/book_rag/parsing/pdf.py) calls pdfium's `get_text_bounded()` for each page, and raises `NoTextError` only when **no** page has text ("scanned PDFs need OCR"). Two cases follow:

1. A fully scanned book fails at upload with `NoTextError`.
2. A mixed book (text pages plus a scanned appendix, a map, a photographed table, a figure whose caption is part of the image) succeeds, but the image pages contribute nothing. The user gets fewer chunks and no warning, and a question about that content is answered from other pages or not at all.

The worker ([`ingest.py`](../../apps/worker/src/book_rag_worker/ingest.py)) runs `parse`, `chunk` and `embed` inside one job (the stage is recorded in `ingestion_jobs.stage`), per [ADR 0004](../adr/0004-ingestion-queue-in-postgres.md). The books are Vietnamese and English, so a reader must handle Vietnamese diacritics (tone marks and vowel marks such as ệ, ữ, ơ).

## Terms

- **Text layer.** The characters a PDF stores as text, with positions. A scan stores a picture instead, so extracting text returns nothing.
- **OCR (optical character recognition).** Software that turns an image of text into characters.
- **Tesseract.** An open-source OCR engine that runs on the CPU, with one trained data file per language (for example `vie` and `eng`).
- **Vision-language model (VLM).** A neural network that takes an image and a prompt and writes text. Used as a reader, it is told to transcribe the page. It can also describe a figure, which OCR cannot.
- **Layout model.** A model that first finds regions on the page (columns, tables, figures) and then reads each region. PaddleOCR is the usual open-source example.
- **Character error rate (CER).** Edit distance between the machine text and a hand-checked transcription, divided by the length of the transcription. Lower is better.
- **Hit@5.** The share of test questions whose correct page appears among the top 5 retrieved chunks (the metric used in [docs/benchmarks](../benchmarks/README.md)).
- **Idempotent stage.** Running it twice gives the same stored result as running it once, so a retry is safe.
- **Hallucination (of a VLM).** Fluent text that is not on the page. OCR makes character errors; a VLM can invent whole lines, which CER catches only partly.

## Requirements

- Detect, per page, whether the text layer is missing or too thin to trust, and record it. Cheap: no model runs on a page that has text. (Functional.)
- Read the flagged pages into text, with the page number kept, so citations ("page 212") still work. (Functional.)
- Vietnamese diacritics must survive: a missing tone mark changes the word, breaks keyword search (BM25, [ADR 0011](../adr/0011-bm25-in-postgres-stored-statistics.md)) and weakens the embedding. (Functional.)
- Fit one 16 GB laptop. The GPU in [compose.yaml](../../compose.yaml) is a 6 GB card that already holds the embedder and the answer model, and any GPU job runs under the machine-wide lock. A reader must not make chat unusable while a book ingests. (Non-functional; the 6 GB figure is quoted from the comment in `compose.yaml`, not re-measured here.)
- Slow work stays off the request path and fits the Postgres queue: retries only for transient failures, no duplicate rows on re-run (ADR 0004).
- Time per page is **to be measured** (see the plan); the budget is set from that measurement, not guessed now.

## Detecting a page that needs reading

Cheap signals, all available from pdfium (already the parser) without running any model:

- **Characters per page** from the text layer (the length of the normalised text the parser already computes). A page under a threshold counts as thin. Real pages with little text exist (a chapter title page, a blank verso), so the count alone is not enough.
- **Image coverage:** the share of the page area covered by image objects (pdfium exposes page objects with their bounding boxes). A scan is one image covering nearly the whole page; a text page with a small logo is not.
- **Combined rule (proposal):** flag a page when its text-layer characters are below T and image coverage is above C. T and C are tuned on the dev pages below, before any reader is chosen, so detection can be judged on its own: precision (flagged pages that really needed reading) and recall (needed pages that were flagged), against pages labelled by hand.
- **A known trap:** a scan that someone already OCR'd carries a text layer behind the picture. Its text may be wrong, but the detector sees characters. Out of scope for the first version; noted as a limit.
- **The trap in the other direction:** a page whose text layer is garbage (wrong font encoding, so the characters are not real letters). The characters-per-page count passes it. A cheap check is the share of characters that are letters or digits; the detector issue adds it only if the labelled pages show the case.

Detection writes a per-page flag and, per book, the count of flagged pages. The upload response and the job status can then say "12 of 300 pages need reading", which removes the silent loss even when no reader is turned on.

## Options in depth

All three read a page image. The page is rendered to a bitmap first (pdfium can do this, so no new PDF library); the render resolution trades accuracy against time and memory and is a parameter in the plan.

**A. Tesseract OCR with `vie` and `eng` packs.**
How it works: a classical recogniser run on the CPU, one language combination per call (`-l vie+eng`). Packs come in a "fast" and a "best" variant ([tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast), [tessdata_best](https://github.com/tesseract-ocr/tessdata_best)); the choice is a measurable parameter.
- Vietnamese diacritics: supported by the `vie` pack; quality on stacked marks (a tone mark plus a vowel mark) is **unmeasured here** and is the first thing the plan tests.
- GPU/RAM: no GPU, so no contention with chat or the lock. CPU and RAM per page are to be measured; pages can run in parallel across worker processes.
- Time per page: to be measured, on CPU.
- Pros: small, deterministic (same image, same text, so the stage is idempotent), no model server, free, easy to run in the worker image (one system package plus a Python wrapper, or the [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) tool).
- Cons: weak on photographs, curved or skewed pages, handwriting, and layouts with columns or tables (reading order can be wrong); reads text only, so a map or figure gives nothing useful.
- Commits us to: a system dependency in the worker image and a language-pack set to maintain.

**B. A small local VLM through Ollama (a Qwen-VL-class model, for example [qwen2.5vl](https://ollama.com/library/qwen2.5vl)).**
How it works: send the page image and a prompt such as "transcribe all text on this page, keep the order" to the Ollama server the app already uses for embeddings and answers. [ADR 0003](../adr/0003-model-provider-interfaces.md) already hides Ollama behind provider interfaces, so a `PageReader` interface would sit beside them.
- Vietnamese diacritics: unmeasured; model-dependent, and a model can silently "correct" or invent text. Must be tested, not assumed.
- GPU/RAM: the heaviest option. Loading a vision model next to the embedder and the answer model on a 6 GB card probably forces models in and out of VRAM (the same swapping `compose.yaml` describes for the answer model), so it runs under the GPU lock and probably not while chat is in use. The memory figure is to be measured.
- Time per page: a generative model writes its output one token at a time and a page image costs many input tokens, so it is likely the slowest of the three; the figure is **not measured**.
- Pros: can also read a table and describe a figure or map, which no OCR does; copes with messy layouts; one reader for all image content.
- Cons: non-deterministic across model versions (and across runs unless the temperature is 0), so a re-run may differ; hallucination risk; the most memory-hungry; ties ingestion to the one shared GPU.
- Commits us to: Ollama as an ingestion dependency (it is already a chat dependency), a pinned model tag, and GPU scheduling for the worker.

**C. A layout and OCR model such as PaddleOCR.**
How it works: [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) detects text regions, then recognises each with a neural model. Whether a recogniser exists for Vietnamese in the current release is unverified here and is checked first. It can run on CPU or GPU.
- Vietnamese diacritics: unmeasured; depends on which recogniser model supports the marks.
- GPU/RAM: runs on CPU, or on the GPU if wanted; expected heavier than Tesseract and lighter than a VLM. To be measured.
- Time per page: to be measured on both CPU and GPU.
- Pros: usually better than Tesseract on photographed and multi-region pages, still deterministic, and returns text with positions (useful to rebuild reading order).
- Cons: a deep-learning framework in the worker image, which has none today; a heavier fit with the uv lockfile; a model download step.
- Commits us to: a second ML runtime in the worker image.

**Not an option: a hosted OCR or vision API.** Paying per page needs the owner's yes (CLAUDE.md, hard limits) and ties the app to a vendor (the README's "Portable" goal). It stays out of the measurement and is the named step-up if local quality fails.

### How a reader fits the queue (ADR 0004)

The fit has the same shape whichever reader is picked:

- **Where it runs.** Reading is slow and unlike the rest of ingestion (OCR is CPU-bound, a VLM is GPU-bound, embedding calls a model server). Inside the `parse` stage of `ingest_book`, one retry restarts all reading of the book. The alternative is a **separate Procrastinate task kind** `read_pages` per book (or per batch of pages) with its own queue, concurrency and timeout: `ingest_book` detects thin pages, enqueues `read_pages`, and the chunk and embed stages run once reading has stored its text. A separate kind lets us cap a GPU-bound reader at one worker without throttling normal ingestion.
- **Idempotency.** A page's read result is stored keyed by `(book_id, page, reader, reader_version)`, so a retry skips pages already read and a re-run replaces rather than duplicates (the rule ADR 0004 uses for chunks). OCR gives the same text on re-run; a VLM may not, so for a VLM the stored result is authoritative and a re-read is explicit.
- **Retries.** Transient failures (Ollama unreachable, memory pressure that clears) are retried as today, at most twice. A page that reads as empty is not an error and is not retried. A page that fails to render is a permanent failure for that page: recorded, and the book continues without it (a book with every flagged page failed still fails the job).
- **Job state.** The stage gains `read`, and the status shows pages read of pages flagged, so a user who uploads a scan sees "being read", not a failure. The rule from [#81](https://github.com/phuchaitt3/book-rag-app/issues/81) is unchanged: a book is searchable only after its latest job `succeeded`.
- **Stuck-job limit.** ADR 0004 fails jobs stuck over 60 minutes. A long scan could exceed that with any reader, so the limit must follow page progress, not a fixed constant (follow-up 5).

## Measurements

None yet. The plan is fixed here, before any result, so a number cannot be picked to suit a preference.

**Held-out pages.** N = 40 pages, set aside and never used to tune the detector, the render resolution or the prompt (tuning uses a separate dev set of 10 pages):

- 20 Vietnamese text pages (clean print, ordinary layout); 8 Vietnamese with harder layout (two columns, a table, headings with stacked diacritics); 8 English text pages; 4 image-only content pages (a map or a photographed table) for the figure questions.
- Each page is hand-transcribed once, by an agent and then checked against the image by the owner, before any reader runs. Pages and transcriptions live in a DVC-tracked data folder (`workflow:dvc`), not in git.

**Where the pages come from (licence).** Only material free to redistribute: public-domain scans from Wikisource or the Internet Archive where the item's own page states a public-domain status, or pages made by ourselves from public-domain or self-written text (print it and photograph it, which also gives the camera and skew conditions that matter). The source URL and licence basis of every page go in a manifest, checked per item at collection time, not assumed from the site. **No copyrighted scan is committed or pushed.** The repository is public, so the page images stay in DVC storage unless the manifest shows each is public-domain.

**Metrics and thresholds (targets fixed now; not results).**

- **Detector:** recall at least 0.95 and precision at least 0.90 on the labelled pages.
- **Reader quality:** CER on the Vietnamese pages at most 0.05. A diacritic-only error rate is reported separately (CER computed after stripping marks from both texts, compared with full CER, shows how much of the error is marks). A reader above 0.05 on the Vietnamese set is rejected for Vietnamese regardless of speed.
- **Retrieval:** Hit@5 on 40 questions written by hand from the held-out pages before any reader runs (one per page, answerable from that page alone), using the existing retrieval benchmark harness ([docs/benchmarks/README.md](../benchmarks/README.md)). The ceiling is the same questions with the hand transcription as the page text. Target: within 0.10 of the ceiling.
- **Cost:** seconds per page and peak RAM and VRAM for each reader, run under the lock wrapper on this laptop (per `workflow:scaling-test`: same settings for every reader, memory checked first). A time budget is set after the first run from what the product needs; until then each reader reports its figure and none is ranked on speed alone.
- **Hallucination check, VLM only:** the owner reads 10 VLM outputs against their images and counts invented lines. Any invented line on a text page disqualifies the VLM as the default reader for text pages.

What the plan cannot show: behaviour on books unlike the sample, handwriting, other languages, a hosted service's quality, or real traffic.

## Recommendation (a proposal, not a decision)

A two-step default, subject to the measurement:

1. Detect thin and image pages in the parser and record the count. No model; it ships first and removes the silent loss by itself.
2. Read flagged pages with **Tesseract (`vie+eng`)** as a separate `read_pages` job kind on CPU. It needs no GPU (no contention with chat or the lock), it is deterministic (safe to retry), and it is the cheapest to scale. If Tesseract misses the CER threshold on the Vietnamese set, the next candidate is the layout model (C) on CPU. The VLM (B) is kept only for pages with a figure, map or table that OCR cannot read, behind the same `PageReader` interface and the GPU lock.

The order follows the project's goals (scalability and operability first): a CPU reader scales by adding worker processes, a VLM only by GPU time. It is reversible: the reader sits behind an interface, and a change of reader is a new `reader_version`, not a schema change.

## At 1000x the load

Here 1000x means 1000 times the scanned pages ingested per day.

1. **Reader throughput breaks first.** At a fixed seconds per page, a day's pages become hours or days of reading. A CPU reader scales by running more worker processes (the queue and per-book lock already allow it); a GPU reader does not, because the GPU is one shared resource. This is the main reason for CPU first.
2. **The stuck-job limit.** A fixed 60-minute sweeper fails big scans; it has to follow page progress.
3. **Page images are large.** A rendered bitmap costs memory; hold one at a time per process and keep none on disk. The original PDF is already in object storage.
4. **Database growth.** Read text is the same order of size as a text page's, plus one result row per page; the queue-table growth in ADR 0004 also rises. Neither is the first limit.
5. **Queue sharing.** Reading jobs must not starve ingestion of text books: a separate queue and concurrency cap.
6. **Quality drift.** Many sources mean many scan conditions, and the held-out set stops being representative. The step is a standing sample re-checked at each reader or language-pack version, not one measurement.
7. **Cost.** A hosted reader costs per page, linearly. It needs the owner's approval and a budget guard first.

## Follow-up issues to file (not filed by this brief)

Filed after this brief merges, one task per issue.

1. **Detect thin and image-only pages in the PDF parser.** Done when: the parser returns a per-page flag from text-layer characters and image coverage; a book with some flagged pages reports the count in the job status and still ingests its text pages; `NoTextError` still fires when every page is flagged and no reader is configured; detector recall and precision on the labelled dev pages are reported.
2. **Collect and label the held-out and dev page sets.** Done when: 40 held-out and 10 dev pages are in DVC storage with a manifest (source URL, licence basis), hand transcriptions checked against the images, and 40 questions with their expected pages; no copyrighted scan is in the repository or its history.
3. **Add the `PageReader` interface and a Tesseract reader as a `read_pages` job kind.** Done when: a Procrastinate task stores per-page text keyed by `(book_id, page, reader, reader_version)`; a retry skips pages already read; the job shows the `read` stage and pages read of flagged; the chunk stage uses the read text with correct page numbers; tests cover a re-run without duplicates and a page that fails to render.
4. **Measure CER and Hit@5 of Tesseract, a layout model and a local VLM.** Done when: `docs/benchmarks/` holds method, environment, raw numbers, seconds per page and peak RAM and VRAM (run under the lock), and each metric against the thresholds in this brief; this brief is updated with the outcome and an ADR records the chosen reader.
5. **Make the stuck-job limit follow page progress for reading jobs.** Done when: a long scan is not failed by the 60-minute sweeper while pages are still being read, and a job that stops making progress still is; a test covers both.

## Risks and open points

- Whether the first version handles a fully scanned book or only mixed books. A fully scanned book is the larger win and the larger cost; the proposal covers both.
- A pre-OCR'd scan with a bad text layer is not detected in version one (see the traps above).
- Any test page whose licence is unclear is left out; the owner decides borderline items.
- The thresholds (CER 0.05, recall 0.95, and the rest) are targets chosen before any data. The owner may change them before the measurement starts, never after.

## Read before deciding

- Tesseract documentation, including languages and data files: <https://tesseract-ocr.github.io/tessdoc/>
- PaddleOCR project and its supported languages: <https://github.com/PaddlePaddle/PaddleOCR>
- Qwen2.5-VL on Ollama (sizes and tags): <https://ollama.com/library/qwen2.5vl>
- OCRmyPDF, which adds an OCR text layer to scanned PDFs: <https://github.com/ocrmypdf/OCRmyPDF>
