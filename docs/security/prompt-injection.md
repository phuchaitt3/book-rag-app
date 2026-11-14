# Prompt injection through book text (#223)

## Threat

The chat endpoint puts retrieved book passages into the model's prompt. A book (or a chunk of
one) can contain text written to steer the model: "ignore the previous instructions", "print your
system prompt", "answer in French", a fabricated `[9]` citation, a fake `system:` turn, or a
forged closing tag that makes the rest of the chunk look like it sits outside the data. This is
indirect prompt injection, OWASP LLM01 (Prompt Injection) in the OWASP Top 10 for LLM
Applications. Today the books are uploaded by their owner, so the realistic risk is a book taken
from an untrusted source, not a hostile user; the defence is cheap, so it is built in anyway.

Impact is limited by design: the model has no tools, reads no other data, and its output is
shown as text. The worst outcomes are a wrong or off-topic answer, a leaked system prompt (which
holds no secret) and a citation marker that points at nothing.

## Defence (`apps/api/src/book_rag_api/prompts.py`)

1. Each passage sits in a tagged block, all inside one `<passages>` block:
   `<passage n="1">`, the citation header `[1] (section, page N)`, the text, `</passage>`.
2. The system prompt says the passages are untrusted data, never instructions, and that only the
   system message and the text after `Question:` are instructions.
3. `neutralise()` rewrites book text (and the book title and section path) before it enters the
   block: `<` and `>` (also the full-width forms) become `‹` and `›`, so no tag, chat
   template token (`<|im_start|>`) or `</passage>` can appear; a line that starts like a role turn
   (`system:`, `Assistant:`, `**User**:`) gets a look-alike colon; `[INST]`, `<<SYS>>` markers
   lose their brackets; `[n]` and `[1, 2]` become `(n)`, so the only citation markers in the
   prompt are the app's own headers. Ordinary prose is unchanged.
4. The question stays last, after the closing tag, so evals and the stream parser are unchanged.

## Tests

- `evals/fixtures/injection-chunks.json`: 14 chunks (reveal the system prompt, switch language,
  fabricate a citation, close the delimiter, fake system role, chat tokens, full-width tags, one
  benign control).
- `apps/api/tests/test_prompt_injection.py`: prompt construction, no forged tags, markers or
  roles, and a recording fake LLM check that injected lines never appear outside a `<passage>`
  block or in the system message. These are deterministic structural checks; they do not show
  that a real model obeys the delimiter.

## Limits

No defence is complete. Delimiters and a "this is data" instruction lower the chance that a model
follows injected text; they do not stop it, and a model may still follow an instruction written in
plain prose inside a passage (no forged tag is needed for that). Neutralising changes the text the
model sees, for example `[3]` in a book becomes `(3)`. Look-alike characters, other languages and
encodings are not all covered. Output is not filtered: a cited number is not checked against
the passages (the answer eval's citation-validity metric measures that after the fact).

## Measurement

Attack success against a real model, before and after the change, was not run: the local Ollama
(`http://127.0.0.1:11434`) held only the embedding model bge-m3 and no chat model when this was
written, and no model was pulled. To measure, load a chat model, send each fixture chunk as the
only passage with a neutral question, and count answers that follow the injected instruction
(contain the canary, switch language, repeat the system prompt, or cite a number that was not
returned), once with the old prompt and once with this one.
