# Does collapsed whitespace hurt retrieval? (issue #152)

Status: **pre-registered, not yet run** (wip: `experiments/book-testset/whitespace.py` is written and lint-clean but unrun; the first run was stopped by memory pressure, the second queued 2 h behind another chat's GPU job and was cancelled. Remaining: run it under the RAM then GPU lock, add a Results section, open the PR) (this section was committed before any result existed; the results section below is added after the run and the commit history shows the order).

Question: the PDF parser (`book_rag.parsing.pdf._norm`) and the page cleaner in this experiment fold every run of whitespace into one space, so paragraph breaks are lost, and a word hyphenated at a line end would be glued or split. Does keeping them change retrieval on the book test set ([book-retrieval.md](book-retrieval.md))?

## What the app does today

- `parse_pdf` runs `_norm` (`re.sub(r"\s+", " ", ...)`) on each page and on each line; line starts are remembered only to place headings. The text of a page is one line of words.
- `chunk_book` ([chunker.py](../../packages/rag/src/book_rag/chunking/chunker.py)) splits on sentence ends (`(?<=[.!?…])\s+`), packs sentences to 1,200 characters with 150 of overlap, and has **no paragraph option**. It keeps any whitespace inside a chunk but treats a newline like a space when splitting.
- Hyphenated line breaks: a PDF line "…thế-" / "kỷ…" becomes "thế- kỷ" after collapsing. This experiment cannot test that (see Limits).

## Design

One book (*Việt Nam sử lược*, Quyển I), one question set (the 208 checked pairs in `questions.jsonl`), the same models, three corpus variants built from the cached Wikisource pages that `fetch_book.py` already downloaded:

| Variant | Text | Chunker |
|---|---|---|
| **A** | current form: every page's text with all whitespace collapsed to single spaces. Built by collapsing B, and checked equal to the committed corpus of #177 (359 chunks). | `chunk_book`, defaults (1,200 / 150) |
| **B** | the same text with each paragraph (line of the source page) separated by one newline instead of one space | the same `chunk_book`, unchanged |
| **B2** (secondary) | B's paragraphs packed whole into chunks of at most 1,200 characters, never crossing a paragraph boundary; a paragraph longer than that goes through `chunk_book`'s sentence splitter. Written in the script only; the app's chunker is not changed. | script |

B differs from A in one character per paragraph break (`\n` for ` `), so `chunk_book` cuts both at the same offsets and the chunk index is the same. B2 changes the chunk boundaries, so its chunk count and sizes differ; that is the only way "keeping paragraph breaks" can matter to a retriever that embeds chunk text.

**Prediction written before running:** B ranks exactly like A. The BM25 tokenizer (`\w+`) ignores a newline, and bge-m3's SentencePiece tokenizer is expected to fold whitespace, so the embeddings should match to rounding. The script measures both (identical token lists, cosine of each chunk's A and B embedding) so the result does not rest on this expectation. Only B2 can differ.

**Gold across variants.** The gold of a question is every chunk whose text, with whitespace collapsed and lowercased, contains the question's evidence sentence (collapsed and lowercased the same way). The script first applies this rule to A and requires it to reproduce the `gold_chunks` stored in `questions.jsonl` for every question; only then applies it to B and B2. A question whose evidence is in no chunk of a variant (a B2 chunk boundary can split it) counts as a miss and is reported by name.

## Pre-registered analysis

- **Arm:** arm 4 of book-retrieval.md: bge-m3 (dense, `max_seq_length` 1024, fp32) + BM25 (k1 = 1.2, b = 0.75, `\w+` lowercase tokens), 30 candidates per list, RRF k = 60. No reranker.
- **Metrics:** Hit@5 and Hit@1 (top 10 ranked, a hit is any gold chunk in the top k), on the 208 seen and the 208 blind questions. Hit@10 and MRR@10 are reported but do not enter the decision.
- **Primary comparison:** B − A (the issue's question). **Secondary, same rule:** B2 − A.
- **Intervals:** paired percentile bootstrap, 2,000 resamples over questions, seed 178, 95%, as in book-retrieval.md.
- **Decision rule:** a difference is called real only if the 95% interval of the paired difference in Hit@5 excludes 0 on at least one of the two sets. Otherwise the result is "no measurable effect". Hit@1 is reported with its interval and read as supporting detail; it cannot make a difference real by itself. With two comparisons, B2 − A is not corrected for multiplicity and is labelled exploratory.
- **Exploratory, not held-out.** The same 208 questions picked the retrieval design (#177, #180). The result says how the variants compare on this set; it is not a held-out estimate.
- **Hardware and cost:** GTX 1660 Ti, run through the GPU and RAM locks; no API calls, no money.

## Limits (known before the run)

- **The book is a clean transcription,** not a PDF. A is made by collapsing, not by a PDF extractor's output. The experiment shows what collapsing the paragraph breaks of already-clean text does to retrieval. It does not show how a PDF extractor's real errors behave: ragged line breaks inside paragraphs, headers and footers, columns, hyphenation, or paragraph breaks the extractor never reported. No real Vietnamese book PDF is available locally and none is downloaded.
- **Hyphenated line breaks are not tested.** The Wikisource text has no line-end hyphenation, and Vietnamese rarely hyphenates at line ends (its syllables are separate words). The old orthography does use hyphens inside compounds ("thế-kỷ"), which BM25's `\w+` splits into the same tokens either way. This is reasoned, not measured.
- One book, 208 questions per set, intervals about ±4 points; questions generated by a model.
