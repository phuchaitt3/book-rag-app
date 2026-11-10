# Study note: where the reranker runs

**For:** [ADR 0009](../adr/0009-reranker-local-tei-service.md)   **Status:** decided in ADR 0009

## Problem

Retrieval returns the 30 best chunks from vector search and the 30 best from full-text search, merged by reciprocal rank fusion (RRF). Both benchmarks show that a cross-encoder reranker over the fused top 20 is the biggest single gain: about +22 points Hit@1 on the book test set ([book-retrieval.md](../benchmarks/book-retrieval.md)). The app had only a fake reranker. The question is where the real model runs, since Ollama cannot serve it and production cannot hold it (ADR 0003).

## Terms

- **Bi-encoder vs cross-encoder.** An embedding model (bi-encoder, here bge-m3) turns the question and each chunk into vectors separately, so chunk vectors are computed once at ingestion and search is a cheap vector comparison. A cross-encoder reads the question and one chunk *together* and outputs one relevance score. It is more accurate because it sees both texts at once. It is also expensive: nothing can be precomputed, so every question costs one model pass per candidate.
- **Reranking depth.** The number of fused candidates the cross-encoder scores. The cost grows linearly with depth, and the gain flattens once the right chunk is almost always inside the depth.
- **Model server.** A separate process that loads a model once and answers HTTP requests (TEI, Infinity, Triton). The app talks to it like any other service.
- **TEI (Text Embeddings Inference).** Hugging Face's server for embedding and reranking models, written in Rust. It runs one model per container and has a `/rerank` route. Each image tag is built for one hardware target (CPU, or one GPU generation).
- **fp32 / fp16.** The number format of the model's weights and arithmetic. fp16 halves the memory and is usually faster on GPUs with fast half-precision units. The GTX 16xx cards lack the tensor cores that make fp16 fast, so here it was about 4× slower.
- **Graceful degradation (fallback).** When an optional step fails, the system returns a worse but valid result instead of an error. Here, the fused order without reranking.

## Requirements

- Functional: score the top `RERANK_DEPTH` fused candidates for each question. An answer must never fail because of the reranker.
- Latency: an answer streams after retrieval, so retrieval time is time to the first token. There is no target yet. As a working bound, the reranker should add no more than a few seconds locally (estimated).
- Memory: the API image and process stay small (production free tier, ADR 0003).
- Dependencies: no new Python dependency for this step (one lockfile change at a time, `CLAUDE.md`).

## Options in depth

**In-process model.** The API loads `CrossEncoder("BAAI/bge-reranker-v2-m3")` from sentence-transformers. Pros: no network hop and nothing extra to run. Cons: torch adds about 2 GB (CPU wheels) to several GB (CUDA) to the API image and a large lockfile change. Each API replica holds its own copy of the model (about 2.2 GB of weights), so scaling the API scales model memory too. A slow rerank also competes with request handling in the same process. Commits us to: shipping the model with every API instance.

**Model server beside the API (chosen).** TEI runs as its own container. The API sends `{query, texts}` and gets scores back. Pros: the API stays a small web process, and the model scales separately from the API (more GPU replicas, or none). The adapter is plain HTTP like the Ollama ones, and the server can be swapped for a hosted endpoint that has the same shape. Cons: another service to run and watch, one network hop (under a millisecond on the Compose network), and the image tag is tied to the hardware. Commits us to: running and sizing a GPU service wherever reranking is wanted.

**Hosted rerank API.** Cohere Rerank, Jina or Voyage rerankers, paid per call. Pros: nothing to run, and it scales on the vendor's side. Cons: money per question, chunks of user books leave our system, and it is a different model whose quality on Vietnamese history text is unmeasured. It needs an arm-5 rerun on the book test set before production may use it, and spending on that run needs the owner's yes.

**No reranker.** Keeps today's code. Loses about 22 points Hit@1. Hit@5 is closer (6 to 7 points), which matters because the prompt takes the top 6 chunks.

## Measurements

Measured 2026-11-10 on the owner's laptop: GTX 1660 Ti 6 GB, Docker Desktop on WSL 2 (12 vCPU, 8 GB for the VM), Ollama serving bge-m3 on the same GPU. Script: [experiments/book-testset/rerank_latency.py](../../experiments/book-testset/rerank_latency.py). It runs the app's own `HybridRetriever` over the book's 359 chunks held in memory (bge-m3 vectors from Ollama, a small BM25 for the text list), on 40 questions sampled with seed 184 from `questions.jsonl`, with 3 warm-up questions, `top_k` 6 and depth 20. Times are per question, for the whole `retrieve` call.

| Setup | p50 | p95 | Hit@1 | Hit@5 |
|---|---|---|---|---|
| Fused, no reranker | 2,360 ms | 2,458 ms | 77.5 | 90.0 |
| + TEI `turing-1.9.4`, fp32, 2,048 batch tokens | 4,940 ms | 5,166 ms | 95.0 | 100.0 |
| + TEI `turing-1.9.4`, fp16 (default), 8,192 batch tokens | 13,553 ms | 13,986 ms | 95.0 | 100.0 |
| + TEI `cpu-1.9.4`, 2,048 batch tokens | about 58 s (3 single calls of 20 pairs: 58.0, 59.1, 59.0 s) | n/a | not run | not run |

- **The reranker adds about 2.6 s at p50 on the GPU in fp32,** close to the benchmark's "about 2 s per question" with sentence-transformers in fp32. In fp16 it adds about 11 s. TEI's Turing image defaults to fp16, so `--dtype float32` matters on this card.
- **Quality matches the benchmark.** Hit@1 95.0 through the app's path, against arm 5's 92.8 on the full seen set. The served model behaves like the benchmarked one. With only 40 questions this is a check, not a new result.
- **Most of the remaining time is the query embedding.** One Ollama `embed` call for a one-line question took about 2.2 s, with or without TEI running ([#185](https://github.com/phuchaitt3/book-rag-app/issues/185)). Search and fusion themselves take a few milliseconds.
- **GPU memory is tight.** Next to Ollama's bge-m3 (0.7 GB), TEI ran out of GPU memory during warmup at its default 16,384 batch tokens (fp16), and at 8,192 and 4,096 in fp32. It started at 2,048. TEI warms up with one input as long as the batch budget, and attention memory grows with the square of the input length, so the batch budget also caps the input length. The book's chunks are far shorter than 2,048 tokens.
- **CPU is not usable for chat:** about a minute per question, using about 6 cores and 5 GB of RAM in the container. The TEI log reports about 22 s of "queue time" even for a single call. That is its internal batching of the 20 pairs into 2,048-token batches, not a backlog of earlier requests.

What this does not show: latency under concurrent questions (all runs were one question at a time); the real app path through Postgres (the searcher here is in memory, so database time is not included); other GPUs; production.

## At 1000x the load

At 1000× the questions (say tens per second instead of a few per minute), in the order things break:

1. **Reranker throughput.** One 1660 Ti does about 8 pairs per second in fp32 (20 pairs in about 2.6 s), so at depth 20 it serves well under one question per second. More load queues inside TEI, and requests then hit `RERANK_TIMEOUT` and fall back, which quietly lowers quality. Next steps: lower the depth (10 keeps most of the Hit@5 gain; measure first), use bigger or more GPUs behind one URL (the server is stateless), or a smaller reranker model.
2. **Silent fallback.** At that rate, falling back must be measured: count fallbacks and alert on the rate, or the system degrades without anyone seeing it.
3. **Cost per question.** On hosted GPUs or a hosted rerank API, the reranker becomes the largest cost per question. Caching scores per (question, chunk) helps only for repeated questions.
4. **Thread per call.** `TeiReranker` runs `urllib` in a worker thread, so the default thread pool caps concurrent reranks at a few dozen per API process. An async HTTP client removes that limit (ADR 0003's next step for all adapters).

## Read more

- Nils Reimers and Iryna Gurevych, "Sentence-BERT" (2019), sections on bi-encoders vs cross-encoders; and the sentence-transformers docs, "Retrieve & Re-Rank": https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Hugging Face, Text Embeddings Inference documentation (supported models, CLI arguments, `/rerank`): https://huggingface.co/docs/text-embeddings-inference
- Michael Nygard, *Release It!* (2nd ed.), chapters on timeouts, circuit breakers and graceful degradation (the fallback pattern used here).
