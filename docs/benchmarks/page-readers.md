# Image-page readers on the #271 page set (#273): PROVISIONAL

Status: **UNCHECKED.** The page set (#271, PR #288) has not had the owner's spot-check or licence
approval. Every number below may change or be discarded. Do not cite it elsewhere.

## Tesseract (vie+eng, 300 dpi setting, tessdata_fast 4.1.0), CPU only

Run: `experiments/pages/reader_cer.py` on the 50 pages (40 held-out, 10 dev), page images as the
1500 px JPEGs from the set. Raw rows: `experiments/pages/results/tesseract-vie-eng-UNCHECKED.json`.
CER is Levenshtein distance over NFC-normalised, whitespace-collapsed text against the proofread
Wikisource text.

| Measure | Value |
|---|---|
| Pages | 50 |
| Micro CER (all pages) | 0.164 |
| Mean per-page CER | 0.184 |
| Median seconds per page | 4.0 |

The worst pages (CER 0.5 to 0.9) are not yet diagnosed: layout (columns, running heads) or a
mismatch between the image and the proofread text are both possible, so a spot-check of those
pages is the first use of the owner's review. No GPU was used; the laptop GPU was capped at 1350 MHz
overnight, which does not apply to this CPU run.

## Not done

VLM reader and Hit@5 on the 40 questions (`experiments/pages/questions.jsonl`): not run.
