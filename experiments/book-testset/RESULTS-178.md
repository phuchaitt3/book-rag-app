# Results for the book test set v2 (issue #178)

Rules: [PREREG-178.md](PREREG-178.md), committed before any of this was generated. Output: [questions.v2.jsonl](questions.v2.jsonl). Everything below was produced by `testset_v2.py` from the committed v1 set and the book text fetched by `fetch_book.py`. Generator and answerer: Claude (Sonnet 5.5); no DeepSeek call, no spend.

**Status: LLM-reviewed only. No person has checked v2.** `questions.jsonl` (v1) is still the published set that `bench.py` and the abstain benchmark use.

## 1. Stronger blind rewrites: partly met

| | v1 blind | v2 blind (kept) |
|---|---|---|
| pairs with a blind question | 208 | 54 of 208 (26%) |
| mean word overlap with source chunk | 0.668 | 0.429 |

- First pass: 31 of 208 under 0.50. The 177 others got the one pre-registered retry: 23 more. 154 pairs have no v2 blind question (their seen question stays).
- **Success rule: not met.** The overlap rule held (kept mean 0.429 against 0.55), but only 26% of pairs kept a rewrite against the 50% required. The threshold was not changed. Mean overlap of all 385 attempted rewrites is 0.66, no lower than v1: most questions name people, places and dates that the answer chunk contains, and those words cannot be dropped without changing the question. Reaching 50% would need a looser threshold (a new pre-registration) or a different measure that ignores names; that is a decision for the user.
- Self-review (same model, not independent): 8 of the 54 rewrites are flagged (`review_flag: true`): c3, c8, c122 (say "this book" without naming it), c26, c27 (swap "móng chân", "nỏ thần" for vaguer words), c33 (tỉnh became "khu vực"), c74 (a named enemy became "giặc ngoài biển"), c84 (assumes a descendant). Left in the file so the human check sees them.
- The author saw the v1 blind rewrites of c0 and c2 before writing; those two pairs got no kept rewrite.

## 2. Closed-book filter

- Claude answered 206 seen questions with no answers shown; 77 were correct by the pre-registered rule (at least 60% of the reference answer's words). Pairs c0, c2 keep their v1 verdict (c6 is not in the set). Together with those two, 78 of 208 are marked closed-book answerable (v1: 88).
- The new count (78) is lower than v1's (88), although the pre-registration expected a stronger model to drop more questions. Claude answered "không biết" or gave a flagged guess ("không chắc") on 52 of 206 questions, and the lexical grader may mark correct paraphrases wrong; both are possible causes and neither was tested. As a result the `*_retrieval_needed` sets are not smaller than v1's. No manual override was applied.
- `closed_book_v1` keeps the old verdict; `closed_book_by` says which model wrote the current one.

## 3. Varied unanswerable questions: met

25 new questions, 6 categories (later 5, figures 5, abroad 4, private 4, false-premise 4, present 3); largest share 20%; 0 mention archaeology; 0 duplicate a hand-written question. Overlap check: one question was replaced (u2-7: its answer was partly in the book as per-mẫu tax rates); u2-15, u2-18 and u2-20 are over 0.80 because of short common words and were read against the chunks: the book does not answer them (u2-18 and u2-20 are false premises: the Lý moved to Thăng Long, not Hoa Lư; Hồ Quý Ly took the Trần throne, not the Lý). Not checked by a person.

## 4. What the user must do (the human check)

Check these in `questions.v2.jsonl`: the 8 flagged rewrites; the 10 control pairs `['c142', 'c315', 'c281', 'c35', 'c2', 'c79', 'c23', 'c65', 'c289', 'c209']` (seen question, answer, evidence, and v2 blind where one exists); about 20 of the 25 new unanswerable questions. Then decide: accept v2, loosen the rewrite threshold (new pre-registration), or keep v1. About 30 minutes.
