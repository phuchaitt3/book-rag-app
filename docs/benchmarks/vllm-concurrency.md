# vLLM (AWQ) against Ollama under concurrent load (#245)

Status: **pre-registered 2026-11-19, before any run.** Results are added in a later section; the
sections above it are not edited after the first run (a change is a dated note below it, and the
numbers it touches are then exploratory).

## Question

The single-request benchmark ([serving-latency.md](serving-latency.md)) cannot show what a
continuous-batching server does. Does vLLM serving an AWQ-quantized Qwen2.5-3B-Instruct keep
latency and throughput better than Ollama serving the same model family at 4 and 16 requests in
flight, on the same GPU?

## Arms

Both on one Kaggle T4 (15 GB, Turing), driven by the same client script and prompts:

| Arm | Server | Weights |
|---|---|---|
| vllm-awq | vLLM 0.10.2 (pinned), `--dtype half --quantization awq --max-model-len 8192 --gpu-memory-utilization 0.85 --max-num-seqs 16`, XFORMERS attention | `Qwen/Qwen2.5-3B-Instruct-AWQ` (4-bit AWQ, from Hugging Face) |
| ollama-q4km | Ollama (version recorded by the run), `OLLAMA_NUM_PARALLEL=16`, `OLLAMA_CONTEXT_LENGTH=8192` | `qwen2.5:3b-instruct` (Q4_K_M GGUF, from the Ollama registry) |

The two are the same model family at nominally the same bit width but **not identical weights**
(AWQ against Q4_K_M); the comparison is of two serving stacks as people would deploy them, not of
one set of weights on two engines. Ollama gets `NUM_PARALLEL=16` so it is not held to its default
single or four slots; that setting is part of the arm.

## Inputs

The 208 questions of `experiments/serving/questions-208.json`. Each prompt is the exact chat
request the app builds (system prompt, six retrieved and reranked passages, question), captured by
pointing the running app at a stub server (`capture_stub.py`, `dump_prompts.py`), so the Kaggle
job needs no database. The prompts file stays out of git (`experiments/serving/data/`, git-ignored);
its sha256 goes in the results section. `max_tokens` 256, temperature 0, same for both arms.

## Procedure

`concurrency_bench.py` sends all 208 prompts at each concurrency C in {1, 4, 16} (a pool of C
workers; a worker sends its next prompt as soon as its previous answer ends), after 4 uncounted
warm-up requests. Each level runs **once** per arm. Request-level statistics use the 208 requests
of a level; the arms are not repeated, so run-to-run variation (other tenants on the host, GPU
clocks) is not measured and is named as a limit.

## Metrics (fixed in advance)

Per level and arm: time to first token (p50, p95), total latency (p50, p95), decode tokens/s per
request (median), aggregate output tokens/s (all tokens over wall time), error count, peak GPU
memory from `nvidia-smi` (whole card, so vLLM's up-front KV-cache reservation shows as peak).
Intervals: 95% percentile bootstrap, 2,000 resamples, seed 259, over the requests of a level.

## Rule for calling a difference real

Per metric and level, the arms differ when **the 95% intervals do not overlap and the point
estimates differ by at least 20%**. Aggregate tokens/s has no interval (one run per level), so a
difference there is reported as a ratio and called real only when the ratio is at least 1.5 and the
request-level metrics at that level agree in direction. Everything else is reported as "no clear
difference". A null or mixed result is a valid finish. Peak memory is descriptive only.

## Expectation (stated before the run, so it can be wrong)

At C=1 the arms are close (within 20%); at C=16 vLLM's aggregate tokens/s is at least 2x Ollama's
and its p95 total latency lower.

## What the numbers cannot show

One model size (3B), one GPU class (T4), two stacks with different quantization formats, a single
run per level, prompts with real retrieval context but answers cut at 256 tokens, no answer-quality
comparison (AWQ and Q4_K_M answers are not graded here), a free shared Kaggle host. They do not say
anything about larger models, Ampere or newer GPUs, or the 6 GB laptop GPU, which cannot hold vLLM
next to the embedder and reranker.

## Reproduce

`python scripts/kaggle_run.py build serving --prompts experiments/serving/data/prompts-208.jsonl`,
then `push`, `wait`. Uses the free weekly Kaggle GPU quota; no paid API.

## Notes after pre-registration

- **2026-11-27, before any run:** since the pre-registration the app refuses a question whose best
  passage scores under 0.2557 and calls no model (#222). To keep 208 prompts, the dump runs with
  both abstain thresholds at -1. Each prompt is still the one the app builds from the retrieved
  passages; the dump records each question's top score, so the number the shipped app would have
  refused is reported with the results.
- **2026-11-27, smoke kernel (8 prompts, not a result):** the Ollama arm answered every request;
  vLLM did not start because transformers 5 was installed. The kernel now pins transformers below
  5. The Ollama arm runs v0.40.13 from a checksummed release instead of the install script. The
  smoke has not been repeated since the pin.
