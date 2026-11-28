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

## Results: Qwen2.5 3B, 2026-11-28 (not the model the app ships)

**Result.** Under load vLLM is ahead of Ollama on a few latency figures and on none of the throughput figures by the rule above. At 16 in flight vLLM's aggregate output rate is 1.15 times Ollama's, not the 2 times expected, and its p95 total latency is not clearly lower. At one request at a time Ollama decodes faster per request (68 against 49 tokens/s). Neither server returned an error in 624 requests.

| In flight | Metric (95% interval) | vLLM, AWQ | Ollama, Q4_K_M | Verdict by the rule |
|---|---|---|---|---|
| 1 | Time to first token p50, s | 1.14 (1.11–1.16) | 1.37 (1.33–1.38) | no clear difference (borderline, see below) |
| 1 | Time to first token p95, s | 1.32 (1.30–1.38) | 1.55 (1.51–1.57) | no clear difference |
| 1 | Total latency p50, s | 1.80 (1.76–1.90) | 1.84 (1.78–1.98) | no clear difference |
| 1 | Total latency p95, s | 4.00 (3.18–5.90) | 3.68 (3.09–5.05) | no clear difference |
| 1 | Decode tokens/s per request, median | 49.27 (49.21–49.37) | 68.26 (68.21–68.34) | Ollama better |
| 1 | Aggregate output tokens/s | 23.4 | 25.2 | ratio 0.93: no clear difference |
| 1 | Errors (of 208) | 0 | 0 | |
| 1 | Output tokens, all requests | 10474 | 10984 | |
| 1 | Peak GPU memory, MiB (descriptive) | 13583 | 6957 | |
| 4 | Time to first token p50, s | 1.17 (1.16–1.19) | 1.50 (1.49–1.52) | vLLM better |
| 4 | Time to first token p95, s | 2.45 (2.30–2.57) | 2.97 (2.83–3.19) | no clear difference (borderline, see below) |
| 4 | Total latency p50, s | 4.37 (4.02–4.74) | 6.03 (5.39–6.73) | vLLM better |
| 4 | Total latency p95, s | 13.99 (12.47–20.04) | 23.41 (18.44–29.48) | no clear difference |
| 4 | Decode tokens/s per request, median | 10.94 (10.47–11.87) | 8.79 (8.09–9.54) | no clear difference (borderline, see below) |
| 4 | Aggregate output tokens/s | 34.0 | 26.7 | ratio 1.27: no clear difference |
| 4 | Errors (of 208) | 0 | 0 | |
| 4 | Output tokens, all requests | 10474 | 11396 | |
| 4 | Peak GPU memory, MiB (descriptive) | 14125 | 6959 | |
| 16 | Time to first token p50, s | 1.37 (1.25–2.06) | 2.33 (2.25–2.67) | vLLM better |
| 16 | Time to first token p95, s | 7.56 (3.75–14.63) | 9.31 (5.75–15.78) | no clear difference |
| 16 | Total latency p50, s | 14.97 (13.57–16.63) | 17.51 (15.93–19.85) | no clear difference |
| 16 | Total latency p95, s | 50.96 (45.58–69.75) | 65.93 (54.35–83.54) | no clear difference |
| 16 | Decode tokens/s per request, median | 2.59 (2.46–2.68) | 2.36 (2.27–2.43) | no clear difference |
| 16 | Aggregate output tokens/s | 38.2 | 33.1 | ratio 1.15: no clear difference |
| 16 | Errors (of 208) | 0 | 0 | |
| 16 | Output tokens, all requests | 10463 | 10771 | |
| 16 | Peak GPU memory, MiB (descriptive) | 14125 | 6961 | |

"Ratio" on the aggregate rows is vLLM divided by Ollama.

**The expectation was wrong.** At one in flight the latency figures are within 20% as expected, but decode speed is not. At 16 in flight vLLM's aggregate rate did not reach 2 times Ollama's.

**Borderline cells.** The rule says "differ by at least 20%" and did not fix which value is the base. Three cells pass against the lower value and fail against the higher one; they are reported as no clear difference: time to first token p50 at 1 in flight (1.14 against 1.37 s), time to first token p95 at 4 (2.45 against 2.97 s), and decode tokens/s at 4 (10.9 against 8.8).

**Conditions.** Kaggle T4 (15 GB, `CUDA_VISIBLE_DEVICES=0`), one kernel running the vLLM arm and then the Ollama arm; repository commit `e95a0db`; vLLM 0.10.2 with torch 2.8.0+cu128; Ollama 0.40.13, which reported 16 slots of 8,192 tokens and truncated no prompt. Prompts file sha256 `fe229f2ef7fe39a70e973dfd470c2620179f4b4e1106fa94394b909414a5c0f0`; abstaining was off for the dump, and the shipped threshold would refuse 10 of these 208 questions.

Raw data in [experiments/serving/results/](../../experiments/serving/results/): `concurrency-vllm-awq*`, `concurrency-ollama-q4km*`, `concurrency-env.txt`.

**Limits found by the run, besides those above.**

- **vLLM ran its older V0 engine.** The kernel sets `VLLM_ATTENTION_BACKEND=XFORMERS` for the Turing card, and vLLM 0.10.2 does not support that in its V1 engine, so it fell back to V0. These figures do not describe the V1 engine or a newer GPU.
- The same 208 prompts were sent at each level, after 4 warm-up prompts taken from them, and neither server's prompt caching was controlled.
- The servers did not produce the same amount of text (10,463 to 11,396 output tokens per level), as their weights differ.
- Peak memory is the whole card: vLLM reserves its key-value cache up front (`--gpu-memory-utilization 0.85`), so it is not what vLLM needs.

