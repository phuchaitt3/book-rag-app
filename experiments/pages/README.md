# Held-out and dev page sets for the image-page reader comparison (#271)

Status: **collected by an agent 2026-11-19; not approved.** The owner's spot-check (about 10 pages
against their images) and the licence approval are still to do. Until then every number computed
on these pages is provisional (#273), and `licence_approved_by_owner` is `false` in the manifest.

Owner's checks so far (2026-11-27, passed on through another chat): pages b00p017, b01p040 and
b04p016 compared with their images and correct (3 of 50 pages, not the planned 10); the Commons
file pages opened for books b00, b05 and b09 look correct. The questions are not checked, and the
licence basis is not approved.

What is here (git): the scripts, the 40 drafted questions (`questions.jsonl`) and the DVC pointer
`data/pages.dvc`. What is not in git: `data/pages/` (images, text, `manifest.jsonl`), which lives in
DVC storage. This repository sets no DVC remote (a remote path is a local setting); set one with
`dvc remote add -d --local <name> <url>`, then `dvc pull`.

## Contents of `data/pages/`

- `images/<id>.jpg`: the scan of one page, rendered at 1500 px width by Wikimedia from the
  Commons PDF (`iiurlparam=pageN-1500px`).
- `text/<id>.txt`: the community-proofread text of that page from Vietnamese Wikisource, cleaned of
  wiki markup (`<poem>`, section marks, rules and spacers). A template keeps its visible text,
  innermost first: `{{g|{{xx-lớn|VI}}}}` becomes `VI`, so chapter headings stay. No `{{` is
  left (`check_questions.py` fails if one is). Rules and their widths are dropped,
  `{{SIC|printed|correction}}` keeps the printed spelling, wiki indent marks are removed, and
  footnote text is moved after the body, without the `(1)` markers, which the wikitext does not
  hold. The running head and page number are not in the text. It is the ground truth for CER
  **after** the spot-check.
- `manifest.jsonl`: per page the source URL, Wikisource revision, proofread level (3 proofread,
  4 validated), image URL and sha256, and the licence basis read from the live Commons file page
  at collection time (licence short name and the `PD-old-*-expired` category).

## Selection

- 10 books (Wikisource Index progress V, "validated", and a `PD-old-*-expired` Commons category;
  1910 to 1925 prints: a novel, translated tales, history, essays, the Analects, women's
  conduct), 5 pages each: 4 held-out, 1 dev (seed 271). 40 held-out and 10 dev pages.
- A page must be proofread or validated, with 600 to 2500 characters of prose after cleaning.
  Verse books were left out because a question cannot be answered from one page of verse reliably.
- Books were found with `scan_candidates.py` (all Index scans with a PD-old category) and
  `progress.py` (the Index progress field). A book flagged "C" in the Index had pages still at
  level 1, so the page level, not the Index flag, decides.

## Questions

`questions.jsonl` has 40 questions, one per held-out page, written by reading that page's text
before any reader ran, each answerable from that page alone (`check_questions.py` checks the
mapping). They were drafted by an agent and are **not yet read by the owner**. Several questions
cite a character or term that also occurs on other pages of the same book; the retrieval benchmark
will show how many are ambiguous, and the spot-check should flag any.

## Run

```
python collect.py <out dir>            # needs network; about 5 minutes, polite rate limit
python collect.py --retext <out dir>   # re-clean text/ from the pinned revisions (#299)
python check_questions.py <out dir> questions.jsonl
```

## Limits

Proofread text can still hold errors (the reason for the spot-check). All pages are quoc-ngu
prints from 1910 to 1925: no handwriting, no modern layout, no figures or tables. The licence
basis is Commons' own statement; whether it is enough is the owner's call.
