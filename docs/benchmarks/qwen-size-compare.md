# Qwen2.5 0.5B against 3B as the local answer model (#287)

**Status: pre-registered; the scripts work; the result run has not been made (stopped 2026-11-19 when the laptop ran low on memory).** The section "Fixed before the run" was committed before any answer was generated for this comparison. Results are added below it and that section is not edited afterwards.

The app's default answer model is `qwen2.5:7b-instruct`, which does not stay loaded next to the embedder on the 6 GB laptop GPU ([serving-latency.md](serving-latency.md), "The 7B default"), so local runs use `qwen2.5:3b-instruct`. Nobody has measured whether `qwen2.5:0.5b-instruct` would be good enough, or what 3B buys over it. This note compares the two on the same questions, book and retrieval.

## Fixed before the run (written 2026-11-19, before any result was seen; not changed afterwards)

**Question.** Is `qwen2.5:0.5b-instruct` as good an answer model as `qwen2.5:3b-instruct` for this app on a 6 GB laptop GPU, and what does 3B cost in time to first token and VRAM?

**Questions asked.** The 248 questions of `experiments/book-testset/questions.jsonl` of kinds `blind` (208, answerable) and `unanswerable` (40), each once per arm, one request at a time, in file order. The 208 `blind` questions carry the answer metrics; the 40 `unanswerable` ones carry the abstention metric. No warm-up exclusion: the first question of each arm may pay the model load and is counted (the arms are compared at the same position, and the load is part of what the user pays).

**Arms.** Same stack, book, embedder and retrieval; only the answer model differs.

| Item | Both arms |
|---|---|
| Book | the Wikisource PDF of *Việt Nam sử lược*, Quyển I, 392 chunks ([e2e-real-model.md](e2e-real-model.md)); SHA-256 recorded with the result |
| Retrieval | through the app's `POST /books/{id}/chat`, hybrid search with the BM25 leg, **reranker off** (`RERANKER_PROVIDER=none`, no reranker container), `top_k` 6 |
| Embedder | `bge-m3` through Ollama |
| Answer model | arm `0.5b`: `qwen2.5:0.5b-instruct`; arm `3b`: `qwen2.5:3b-instruct`; both Q4_K_M through Ollama 0.40.13 |
| Sampling | temperature 0, seed 287, `num_ctx` 4096. The app sends no sampling options, so both are set in a local Ollama alias (`ollama create` from a Modelfile with `FROM <model>` and three `PARAMETER` lines); no app code changes and no download |
| Ollama | a separate `ollama serve` per arm on its own port, started fresh and stopped after the arm, so one arm's model is never resident in the other (this keeps the VRAM peak per arm clean) |
| GPU | the GPU clock cap that is already on stays on; the GPU lock (`gpu_run.py`) wraps each run |
| Order | `0.5b` first, then `3b`, on one ingested book. Not interleaved; the arms run minutes apart. |

The existing 3B records (the 208-question serving run of [serving-latency.md](serving-latency.md)) hold timings only, not answers, so 3B is run again here under identical conditions.

**Metrics.** From [evals/answer_eval.py](../../evals/answer_eval.py) (its `score_stream` and summary code are imported, not copied), plus cost. All rates are over the stated denominator; every interval is a 95% bootstrap over questions (10,000 resamples, seed 287).

| # | Metric | Denominator | Role |
|---|---|---|---|
| P | **Cited-answer hit:** the answer carries a valid `[n]` marker and a cited chunk contains the question's evidence sentence | 208 blind | primary (no judge) |
| S1 | **Cites a retrieved passage:** at least one valid `[n]` marker, i.e. the citation-marker rate | 208 blind, not abstained | secondary |
| S2 | **Correct abstention:** on an unanswerable question, either the app's threshold abstained (the model is not called, so this part is the same for both arms by construction and is reported only as a check) or the answer refuses (regular expression below) | 40 unanswerable | secondary |
| S3 | Token F1 against the reference answer | 208 blind | secondary |
| S4 | Format errors and stream errors | 248 | check |
| J | **Judge score**, 1 to 5, from [judge.md](judge.md)'s rubric, one pass (temperature 0, seed 244), over all 248 answers of each arm, shown the passages the answer cites | 248 | **exploratory, never decides** |
| C1 | **Time to first token** from just before the request to the first `token` event: median and p90 | 248 | cost |
| C2 | Whole-answer time: median and p90 | 248 | cost |
| C3 | **Peak VRAM** of the GPU (nvidia-smi, polled every 0.5 s from the arm's start to its end, all processes together, so it includes the embedder) | the arm | cost |

The refusal regular expression, fixed now and applied to the lowercase NFC answer: `không (tìm thấy|có (thông tin|câu trả lời|đề cập|nói)|đề cập|nêu|rõ)|không được (nêu|đề cập)|(do(es)? not|no) (contain|seem|answer|information|passage)`. It is a heuristic and will miss refusals in other words; the judge's score on these 40 is shown beside it.

**Judge caveats, stated up front.** The judge is `qwen2.5:3b-instruct`, the same model as the 3B answerer, so it may prefer its own phrasing: **judged results are exploratory**. The judge is also not yet checked against human labels (#251, [judge.md](judge.md): "UNVALIDATED"); its scores are bimodal and it rated `topk1` answers above `topk6` ones. The judge is run after the arm's generation, with the arm's Ollama stopped, so it does not touch the VRAM and time figures.

**When a difference is real.** For each metric the paired difference 3B minus 0.5B is computed on the same questions (bootstrap over questions, same resamples for all metrics). A difference is **real** when its 95% interval excludes zero. It is **meaningful** when it is also at least 5 percentage points (rates), 0.5 points (judge score) or 0.05 (token F1, in its own 0 to 1 units). A smaller but real difference is reported as real and small. For cost, the medians are compared with their own intervals and called different only when the intervals do not overlap.

**Verdict rule** (applied mechanically to P, S1, S2, S3; J and the cost figures are reported but do not decide):

1. If the interval of P (3B minus 0.5B) excludes zero in favour of 3B: **3B is the better default**.
2. Else if the whole interval of P lies inside ±5 points **and** none of S1, S2, S3 shows a meaningful, real advantage for 3B: **0.5B is good enough on this task and is the lighter, faster default**, subject to the limits below.
3. Otherwise (the P interval is wider than ±5 points, or a secondary metric favours 3B meaningfully, or 0.5B is better on P with a real difference): **the data cannot tell**, or the result is mixed; the note then says which metrics point which way.

A null or mixed result is a valid finish.

**Exit rule.** Each arm ends when all 248 questions have been sent once. A question that errors counts as an error, not retried and not dropped. If a run is killed for low memory, work stops and the kill is reported; an arm may be rerun from the start once, and only for an infrastructure fault (stack not up, killed process, port clash), never after looking at its results. If the stack or a model cannot be brought up, the comparison is not made and this note says so. A short smoke run (a few questions through every step) comes first; its numbers are not results and are not kept. No paid API is called.

**Not planned.** A second book or language, the 7B model, the reranker, a judge from another model family, and human labels (#251).

### Amendment, 2026-11-19, after the smoke run and before any result run

A 5-question smoke run (not a result, nothing from it is kept) showed that a cold start breaks the first questions of an arm: the first question got a 503 after about 21 s (the app's retrieval timeout while `bge-m3` loaded) and the second a stream error (the answer model was still loading). Counting these as the arm's errors would measure the harness, not the model. The rule "no warm-up exclusion" above is therefore replaced by: before each arm, both models (`bge-m3` and the arm's answer model) are loaded by one direct call to Ollama (4 tokens, not through the app), and every one of the 248 questions is then counted. The load times of that call are reported as a cost (they are model-load times, not serving times). Nothing else above changes.

## Results

Not run yet. A first 5-question smoke run passed end to end (stack, ingest in 303 s, both arms, judge, report). A second smoke run, made to check the warm-up amendment, was killed by Claude Code for low memory (about 2.5 GB free RAM with other chats running); the stack and the run's Ollama were torn down. To finish: when the laptop has well over 6 GB free, run `python ~/claude-config/scripts/gpu_run.py run --wait -- "C:/Program Files/Git/bin/bash.exe" experiments/qwen_size/run.sh` (needs the PDF at `experiments/e2e/data/vsl.pdf`, about 70 minutes), then fill this section from `experiments/qwen_size/results/report.md`.
