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
<!-- numcheck: ok: thresholds of a decision rule fixed before the run, not measured figures -->

## Expectation (stated before the run, so it can be wrong)

At C=1 the arms are close (within 20%); at C=16 vLLM's aggregate tokens/s is at least 2x Ollama's
and its p95 total latency lower.
<!-- numcheck: ok: an expectation stated before the run, not a measured figure -->

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

**Result.** Under load vLLM is ahead of Ollama on a few latency figures and on none of the throughput figures by the rule above. At 16 in flight vLLM's aggregate output rate is 1.15 times Ollama's, not the 2 times expected, and its p95 total latency is not clearly lower. At one request at a time Ollama decodes faster per request (68 against 49 tokens/s). Neither server returned an error in its 624 requests.

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

## Amendment, 2026-11-28: the same comparison on the shipped model size

Written after the 3B results above and before any 0.5B run.

- **Why:** on 2026-11-28 the app's default answer model became `qwen2.5:0.5b-instruct`, and a number is reported for the model that ships. The 3B comparison no longer describes it.
- **Change:** only the weights. vLLM serves `Qwen/Qwen2.5-0.5B-Instruct-AWQ`, Ollama serves `qwen2.5:0.5b-instruct`. Prompts file, server flags, levels, metrics, intervals, the rule for a real difference (including the reading of "20%" as against the higher value too) and every limit stay as above.
- **Expectation, so it can be wrong:** the smaller model leaves more of the card for the key-value cache and spends less time per token, so the gaps at 16 in flight stay about the same size or shrink; vLLM's aggregate rate stays under 2 times Ollama's.
- **Which figures answer #245:** both, each labelled with its model.

## Results: Qwen2.5 0.5B, 2026-11-28 (the model the app ships)

**Result.** With the 0.5B model the lead reverses with load. At 16 requests in flight Ollama's aggregate output rate is 1.63 times vLLM's (255.1 against 156.5 tokens/s), and it is better on three of the four latency figures and on decode speed. At one request at a time vLLM sends the first token sooner and Ollama decodes faster per request. No request failed in either arm (624 requests each).

| In flight | Metric (95% interval; n = 208 requests per level) | vLLM, AWQ | Ollama, Q4_K_M | Verdict by the rule |
|---|---|---|---|---|
| 1 | Time to first token p50, s | 0.19 (0.19–0.19) | 0.32 (0.32–0.32) | vLLM better |
| 1 | Time to first token p95, s | 0.23 (0.22–0.24) | 0.36 (0.35–0.36) | vLLM better |
| 1 | Total latency p50, s | 0.35 (0.34–0.36) | 0.41 (0.39–0.42) | no clear difference |
| 1 | Total latency p95, s | 1.07 (0.62–1.75) | 0.84 (0.65–1.35) | no clear difference |
| 1 | Decode tokens/s per request, median | 144.72 (143.25–145.61) | 205.81 (203.31–207.37) | Ollama better |
| 1 | Aggregate output tokens/s | 85.2 | 69.9 | ratio 1.22: no clear difference |
| 1 | Errors (of 208) | 0 | 0 | |
| 1 | Output tokens, all requests | 7549 | 6654 | |
| 1 | Peak GPU memory, MiB (descriptive) | 13555 | 2225 | |
| 4 | Time to first token p50, s | 0.23 (0.22–0.24) | 0.14 (0.13–0.16) | Ollama better |
| 4 | Time to first token p95, s | 0.53 (0.43–0.58) | 0.25 (0.23–0.28) | Ollama better |
| 4 | Total latency p50, s | 0.78 (0.73–0.87) | 0.51 (0.45–0.57) | Ollama better |
| 4 | Total latency p95, s | 3.10 (1.97–4.40) | 3.03 (1.53–5.37) | no clear difference |
| 4 | Decode tokens/s per request, median | 45.28 (42.01–51.03) | 53.63 (52.39–54.40) | no clear difference |
| 4 | Aggregate output tokens/s | 135.9 | 164.1 | ratio 0.83: no clear difference |
| 4 | Errors (of 208) | 0 | 0 | |
| 4 | Output tokens, all requests | 7551 | 7130 | |
| 4 | Peak GPU memory, MiB (descriptive) | 13679 | 2229 | |
| 16 | Time to first token p50, s | 0.42 (0.39–0.43) | 0.21 (0.20–0.23) | Ollama better |
| 16 | Time to first token p95, s | 1.31 (0.89–2.47) | 0.68 (0.48–0.69) | Ollama better |
| 16 | Total latency p50, s | 2.51 (2.33–2.69) | 1.10 (0.96–1.30) | Ollama better |
| 16 | Total latency p95, s | 10.33 (6.94–14.82) | 6.98 (3.93–9.13) | no clear difference |
| 16 | Decode tokens/s per request, median | 11.17 (10.79–11.55) | 19.47 (18.45–20.54) | Ollama better |
| 16 | Aggregate output tokens/s | 156.5 | 255.1 | ratio 0.61: Ollama better |
| 16 | Errors (of 208) | 0 | 0 | |
| 16 | Output tokens, all requests | 7502 | 6499 | |
| 16 | Peak GPU memory, MiB (descriptive) | 13805 | 2229 | |

"Ratio" on the aggregate rows is vLLM divided by Ollama.

**The expectation was wrong** (n = 208 per level). It said the gaps at 16 in flight would stay about the same or shrink. vLLM's aggregate rate did stay under 2 times Ollama's, but the order reversed: with 3B it was 1.15 times Ollama's, with 0.5B it is 0.61 times.

**No borderline cell** in this run (n = 208 per level): no verdict depends on which value the 20% is taken against.

**Conditions.** As for the 3B run: Kaggle T4 (15 GB), one kernel (`serving-05b`) running the vLLM arm and then the Ollama arm; repository commit `42d60a7`; vLLM 0.10.2 with torch 2.8.0+cu128 and `Qwen/Qwen2.5-0.5B-Instruct-AWQ`; Ollama 0.40.13 with `qwen2.5:0.5b-instruct`, 16 slots of 8,192 tokens, no prompt truncated (n = 628 requests including warm-up). Same prompts file (sha256 above). Reproduce with `python scripts/kaggle_run.py build serving-05b --prompts experiments/serving/data/prompts-208.jsonl`, then `push serving-05b` and `wait serving-05b`.

Raw data in [experiments/serving/results/](../../experiments/serving/results/): `concurrency-05b-*`.

**Limits found by the run, besides those of the 3B section** (which hold here too, including vLLM's V0 engine).

- One run per level, so the aggregate ratios have no interval.
- The servers produced different amounts of text (6,499 to 7,551 output tokens per level over n = 208 requests; vLLM produced more at every level), so total latency compares answers of different lengths.
- The cause of the reversal was not investigated. These figures do not show that Ollama is the faster server for small models in general.
- Answer quality of neither 0.5B arm is graded here (#287).

## What this means for the app

The app ships `qwen2.5:0.5b-instruct` on Ollama. On this evidence (n = 208 questions per level, one T4) there is no throughput reason to move it to vLLM: vLLM did not do better under load, and it reserved about 13.8 GiB of the card against Ollama's 2.2 GiB (its reservation is a setting, not a need).
