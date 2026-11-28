# Image-page readers on the #271 page set (#273): PROVISIONAL

Status: **partly checked.** The owner approved the page set's licence basis and checked 3 of the 50
pages against their images and 10 of the 40 questions (2026-11-27, #288); no correction was needed.
The other pages are as proofread on Wikisource and cleaned by the script. Say so wherever a number
from this page set is cited.

## Tesseract (vie+eng, 300 dpi setting, tessdata_fast 4.1.0), CPU only

Run on 2026-11-27: `experiments/pages/reader_cer.py` on the 50 pages (40 held-out, 10 dev), page
images as the set's JPEGs (a 1500 px width was requested; Wikimedia served 25 pages at
1920 px, 10 at 1280 px and 15 at 960 px, n = 50). Tesseract 5.4.0.20240606 on Windows, this laptop (GPU
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

## Layout model: PaddleOCR's stock recognisers cannot write Vietnamese (checked 2026-11-27)

A recogniser can only output characters in its dictionary. The `character_dict` in the shipped
`inference.yml` of `latin_PP-OCRv5_mobile_rec`, `PP-OCRv6_medium_rec` and `PP-OCRv6_small_rec`
(from `huggingface.co/PaddlePaddle`) was compared with the 54,649 non-space characters of the 50
page texts. Missing from the dictionary: 13.0%, 12.6% and 12.6% of those characters, mostly
vowels with two marks (ế, ờ, ấ, ạ, ớ, ả, ộ). PaddleOCR does accept `lang="vi"`
(`paddleocr/_utils/langs.py`), which selects such a model.

(standard: findings/ocr-vietnamese-character-coverage, checked 2026-11-27)

So these readers have a CER of at least about 0.126 on this set before any other error, above the
0.05 target and above Tesseract's 0.111. They are not run. Not covered: a PaddleOCR text detector
with a Vietnamese recogniser from elsewhere (for example VietOCR), or a fine-tuned model.

## Plan for the VLM reader (written before any VLM run; not run)

Model: Qwen2.5-VL-3B-Instruct, temperature 0, one fixed prompt asking for a transcription in
reading order with nothing added. Prompt and image size are chosen on the 10 dev pages only.

1. **Quality screen, Kaggle T4.** `transformers`, full precision (fp16), the 50 page images. The
   kernel downloads them from the image URLs in the manifest and checks each sha256, so no data is
   uploaded. It returns the raw text and seconds per page; scoring runs locally with
   `reader_cer.py`'s normalisation. Estimate 45 to 60 minutes (not measured): a daytime push asks
   first. A smoke run of one page comes first.
2. **Only if held-out micro CER is at most 0.05:** the same model as the app would serve it
   (Ollama `qwen2.5vl:3b`, 4-bit) on this laptop under the GPU lock: CER on the 40 held-out pages,
   seconds per page, peak VRAM and RAM. If the full-precision screen fails, stop: the 4-bit model
   is not run.
3. **Hit@5 on the 40 questions**, local, for the ground-truth text (ceiling), Tesseract's text and
   the VLM's text, with the existing retrieval harness. Target: within 0.10 of the ceiling.
4. **Hallucination check:** the owner reads 10 VLM outputs against their images and counts
   invented lines; any invented line rejects it as the default for text pages.

Reporting: held-out micro CER with a 95% bootstrap interval resampling the 10 books (seed 273),
because pages of one book are not independent; the same interval for Tesseract; and the paired
difference. A diacritic-stripped CER is reported beside the full one, as the brief asks. The set
holds only Vietnamese prints of 1910 to 1925, not the brief's mix of layouts and languages.

## Not done

VLM reader and Hit@5 on the 40 questions (`experiments/pages/questions.jsonl`): not run. No Kaggle
runner for the reader exists yet.
