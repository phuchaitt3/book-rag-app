# Tool-using agent over the MCP tools against single-shot chat (#243)

**Result.** On 40 compound two-part questions, a `qwen2.5:3b-instruct` agent that drives the MCP tools (`search_book`, `get_passage`) for up to 4 steps finds both evidence sentences for **45.0%** of questions (95% CI 30.0 to 60.0). A single search with the compound question (top_k 6) finds both for **42.5%** (27.5 to 57.5). The difference is +2.5 points (-15.0 to +17.5): **no measurable gain**, at twice the tool calls and three times the mean latency. A control that only asks for more passages (one search, k 12, no model) reaches **65.0%** (50.0 to 80.0) in 0.4 s, so on this set the better lever was a larger `k`, not an agent.

## Conditions

| Item | Value |
|---|---|
| Commit | `fb14589` (agent and harness; this note, the tests and the results file come after it) |
| Model | `qwen2.5:3b-instruct` (Q4_K_M) through Ollama, temperature 0, context 8192, for the agent and for the single-shot answer |
| Tool protocol | JSON actions with schema-constrained output (`mode json`), see "Tool calling" |
| Step cap | 4 tool-calling turns, then one forced answer with no tools (at most 5 model calls) |
| Retriever | the app's hybrid search, reranker off, the same code for all arms (the agent through the MCP server over stdio, single-shot through the API) |
| Book | the PDF of *Việt Nam sử lược*, Quyển I, as in [e2e-real-model.md](e2e-real-model.md); real `bge-m3` through Ollama; stack from `compose.yaml` |
| Machine | Windows 11 laptop, GTX 1660 Ti 6 GB, 16 GB RAM; one question at a time under the machine-wide GPU lock |
| Questions | 40 pairs (seed 243) of the 208 blind questions; the pairs are in the [results file](../../experiments/agent/results/agent-eval-qwen3b-json.json) |
| Date | 2026-11-14 |

## The question set, and what it is not

The committed test set has single-chunk questions only; the multi-chunk set (#183) does not exist. [evals/agent_eval.py](../../evals/agent_eval.py) builds a deterministic set: it takes the blind questions whose evidence sentence is inside one chunk of the ingested book, shuffles them with seed 243 and pairs them off, requiring different chunks. The two questions become one: "Hãy trả lời cả hai câu hỏi sau. (1) ... (2) ...". **The two parts are independent, so this is a two-part question, not a dependent multi-hop one**: nothing in part 2 needs the answer to part 1. It tests whether an arm retrieves for both parts, which is the case an agent that splits a question should win.

A part is a hit when its evidence sentence is in a chunk the arm presented (same text matching as [retrieval_check.py](../../experiments/e2e/retrieval_check.py)); a question is a hit when both parts are.

- **Presented** (headline): single-shot, the 6 chunks of the `citations` event; agent, every chunk its searches and reads returned (mean 5.8 chunks); control, 12.
- **Cited**: only chunks the answer cites with `[n]` markers (the control has no answer).

## Results

n = 40 questions, bootstrap 95% intervals (10,000 resamples of questions, seed 243).

| Arm | Both hit, presented | Per-part hit, presented | Both hit, cited | Per-part hit, cited |
|---|---|---|---|---|
| Single-shot (top_k 6) | 42.5% (27.5–57.5) | 65.0% (55.0–75.0) | 17.5% (7.5–30.0) | 33.8% (23.8–43.8) |
| Agent (cap 4) | 45.0% (30.0–60.0) | 62.5% (51.2–72.5) | 10.0% (2.5–20.0) | 31.2% (21.2–41.2) |
| Control: one search, k 12 | 65.0% (50.0–80.0) | 81.2% (72.5–90.0) | n/a | n/a |

Paired difference, agent minus single-shot, in points: both hit, presented +2.5 (-15.0 to +17.5); both hit, cited -7.5 (-22.5 to +7.5). Neither excludes zero.

| Arm | Tool calls per question | Latency, mean (95% CI) | Latency, median | Answers with no `[n]` marker | Token F1 | Reference recall |
|---|---|---|---|---|---|---|
| Single-shot | 1 (the search inside chat) | 16.3 s (15.9–16.6) | 16.3 s | 20% | 0.15 (0.11–0.20) | 0.41 (0.31–0.51) |
| Agent | 2.0 (1.6–2.5) | 49.9 s (27.1–79.4) | 17.5 s | 20% | 0.15 (0.11–0.19) | 0.40 (0.32–0.49) |

Token F1 and reference recall are the [answer_eval](../../evals/answer_eval.py) overlap metrics against the two reference answers joined. They are weak here (a short reference against a long answer) and do not separate the arms. No invalid `[n]` marker occurred in either arm.

## What the agent did

- 23 of 40 questions: one search, then an answer (the model did not split the question). 6 of those found both parts.
- 17 questions used 2 to 4 calls; 12 of them found both parts. 11 hit the step cap and were forced to answer; 8 of those 11 still found both. So the multi-step runs score higher, but they are the questions where the first search failed to satisfy the model, and the sample cannot say the extra steps caused it.
- **4 questions ended in a timeout** (the 300 s request limit of the Ollama client: the model kept generating). They count as misses with whatever they had seen, and they are why the mean latency (49.9 s) is far above the median (17.5 s). The other 36 questions found both parts for 41.7%.

## Tool calling

The first try used Ollama's native tool calling. With `qwen2.5:3b-instruct` it was unreliable: in a 4-question pilot 3 of 4 runs made no tool call and answered "not found", even with "always search first" in the prompt. A plain `format: json` was no better (malformed objects such as `{"": "action"}`). The benchmark therefore uses a JSON action protocol with a JSON schema passed as Ollama's `format` (constrained decoding): each turn is one of `search_book` (query required), `get_passage` (chunk_id required) or `answer`. Native mode is still in the code (`mode native`) and was not benchmarked. Two further adaptations: passages are numbered `[n]` (one number per chunk for the run) because the 3B model corrupts UUIDs, and the harness, not the model, calls the MCP `cite` tool at the end for the numbers the answer cites. So the model sees two of the three tools.

## Limits

- 40 questions, one run, one model, one book, one machine. The intervals are wide (about ±15 points): the agent and single-shot are not shown to differ either way, and a gain of 10 to 15 points would not have been detected.
- Independent parts, not dependent hops (see above). A harder set (#183) may favour the agent.
- A 3B model is a weak planner. A larger model may split questions better; the 7B model does not stay loaded next to `bge-m3` on this 6 GB GPU ([serving-latency.md](serving-latency.md)).
- The prompt was adjusted once after a 6-pair pilot whose pairs are part of the 40 (a sentence telling the model to search each numbered part separately), so the agent had a small advantage the single-shot arm did not.
- Presented chunks favour the agent slightly (variable count, mean 5.8 against 6) and the control strongly (12). The "cited" columns are the stricter reading: they depend on the 3B model writing `[n]` markers, and 20% of answers have none.
- Latency is wall time on a shared laptop; the agent's mean is dominated by 4 timeouts.
- No paid API. Single-shot answers come from the app's chat endpoint with the 3B model (reranker off).

## Reproduce

```sh
uv run python experiments/e2e/fetch_pdf.py
LLM_MODEL=qwen2.5:3b-instruct docker compose -p agent243 up -d --build db s3 migrate api worker
# upload the PDF (see e2e-real-model.md), wait for the ingestion job to succeed
BOOK_ID=<uuid> LABEL=qwen3b-json MODE=json \
  python ~/claude-config/scripts/gpu_run.py run --wait -- uv run python evals/agent_eval.py
docker compose -p agent243 down
```

Code: [evals/book_agent.py](../../evals/book_agent.py) (the loop), [evals/agent_eval.py](../../evals/agent_eval.py) (pairs, arms, scoring), tests in `apps/api/tests/test_book_agent.py` (scripted fake model, including the step cap). Raw per-question records: [agent-eval-qwen3b-json.json](../../experiments/agent/results/agent-eval-qwen3b-json.json).
