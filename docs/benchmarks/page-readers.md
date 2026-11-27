# Image-page readers on the #271 page set (#273): PROVISIONAL

Status: **UNCHECKED.** The page set (#271, PR #288) has not had the owner's spot-check or licence
approval. Every number below may change or be discarded. Do not cite it elsewhere.

## Tesseract (vie+eng, 300 dpi setting, tessdata_fast 4.1.0), CPU only

Run on 2026-11-27: `experiments/pages/reader_cer.py` on the 50 pages (40 held-out, 10 dev), page
images as the 1500 px JPEGs from the set. Tesseract 5.4.0.20240606 on Windows, this laptop (GPU
capped at 1350 MHz, CPU turbo off; no GPU used). Raw rows:
`experiments/pages/results/tesseract-vie-eng-UNCHECKED.json`. CER is Levenshtein distance over
NFC-normalised, whitespace-collapsed text against the proofread Wikisource text.

| Measure | All pages (n = 50) | Held-out (n = 40) | Dev (n = 10) |
|---|---|---|---|
| Micro CER | 0.111 | 0.113 | 0.104 |

Mean per-page CER (n = 50) is 0.113 and the median time is 3.8 seconds per page (n = 50). By page:
3 below 0.05, 38 from 0.05 to 0.15, 9 from 0.15 to 0.30, none above 0.30. No intervals are computed.

Against the brief's target (CER at most 0.05 on the Vietnamese pages), Tesseract does not pass on
this set, provisionally.

### Correction to the first run

The first run (2026-11-19) reported micro CER 0.164 (n = 50). The OCR output of this run is
identical to it on all 50 pages; the difference is the ground truth. The page-set cleaner had
dropped headings and left markup in the text (#299), fixed in PR #315. Do not use 0.164.

## Limits

- The text has no running head or page number, so a reader that reads them is charged for them.
- Wikisource's proofread text drops the space the print puts before `;`, `:`, `?` and `!`. Ignoring
  that spacing in both texts gives micro CER 0.108 instead of 0.111 (n = 50). The metric above
  counts it.
- Footnote text is placed after the body, and the `(1)` markers on the page are not in the text.
- b02p096, the worst page (0.30), matches its scan; Tesseract read lines out of order. The other
  pages above 0.15 are not diagnosed.

## Not done

Layout model, VLM reader and Hit@5 on the 40 questions (`experiments/pages/questions.jsonl`): not
run.
