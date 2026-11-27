# Brief: a free API host with no card

**Needed for:** [#305](https://github.com/phuchaitt3/book-rag-app/issues/305), which re-plans [#23](https://github.com/phuchaitt3/book-rag-app/issues/23)   **Status:** draft; recommendation below, owner decides on #23. Nothing is deployed. Vendor facts checked 2026-11-24 on the pages linked; free tiers change often, so recheck before the deploy.

## Problem

#23 planned Cloud Run for the API, which needs a billing account with a card. The project rule is free tiers with no card. Which free host runs the API container, and what does the web app show while that host is asleep?

## Requirements

- No card at signup, and no way to be billed by surprise (a hard stop at the limit is fine).
- Runs `apps/api/Dockerfile` as it is: Python 3.12 slim, uvicorn, reads `PORT` (default 8080), no local model in the image (embeddings and chat go to a model server by URL, `config.py`). Memory use of the API process is not measured; this brief assumes a few hundred MB and the deploy task must measure it.
- Keeps Vercel (web) and Neon (Postgres) unchanged: both are outside this question.
- Cold start is acceptable if the web app shows a "waking up the server" state and retries `/readyz`.
- Not covered here: the ingestion worker (`procrastinate`, a separate process in `compose.yaml`), the embedding and chat model server (Ollama today), S3 storage. None of the free web-service tiers below runs a worker, and a hosted model and storage need their own no-card answer. These are follow-up questions for the deploy task, not decided here.

## Options

| Host | No card? | Free limits | RAM / CPU | Idle behaviour |
|---|---|---|---|---|
| [Render](https://render.com/docs/faq) free web service | Yes ([Render](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026)) | 750 free instance hours a month per workspace; over the included bandwidth with no card the services are suspended for the month (FAQ) | 512 MB, 0.1 CPU (third-party figure; confirm on the instance-types page) | Spins down after 15 min without traffic; about a minute to wake (FAQ) |
| [Hugging Face Spaces](https://huggingface.co/docs/hub/en/spaces-overview), Docker | No for Docker: the docs say Docker Spaces need a paid plan; community reports show HTTP 402 on cpu-basic | cpu-basic is free hardware, but Docker creation is gated | 2 vCPU, 16 GB | Sleeps after 48 h idle, fixed on free hardware |
| [Koyeb](https://www.koyeb.com/docs/faqs/pricing) Free Instance | No: the pricing FAQ says a card is needed (a $29 pre-authorisation hold, cancelled at once); the web service itself is never charged | One Free Instance per organisation, one region (Frankfurt or Washington), no Worker service ([instances](https://www.koyeb.com/docs/reference/instances)) | 512 MB, 0.1 vCPU, 2 GB disk | Scales to zero after 1 h idle |
| [Fly.io](https://fly.io/docs/about/free-trial/) | Trial only: $1 credit for 7 days with no card; the [free plan](https://docs.fly.io/about/free-plan) ($5 a month) needs a card | Trial: up to 10 Machines | Machine sizes are paid | The pricing page says card required, the trial page says no; sources disagree |
| [Railway](https://docs.railway.com/pricing/free-plan) | Yes (docs: Free plan, no card) | $1 of usage credit each month, no rollover; 30-day trial with $5 one-off ([trial](https://docs.railway.com/reference/pricing/free-trial)) | Trial: 1 GB, shared vCPU (the pricing page says 2 vCPU; sources differ) | Running deployments stop when credit ends; $1 a month is small for an always-on service, hours not computed here |

**Render free web service.** Fits the image with no change: Docker deploys are supported, it sets `PORT` for the service, and the API holds no model. Stateless API, so spin-down loses nothing. Risks: 512 MB is tight if memory use is above the assumption (to measure); 0.1 CPU makes the one-minute wake slower, because importing the app and opening the database pool happens inside it; the monthly hours cover one always-awake service, so spin-down is what keeps it inside the allowance; no worker process on the free tier. Free Render Postgres is not wanted (1 GB, expires after 30 days), Neon stays.

**Hugging Face Spaces.** The best hardware by far, but Docker Spaces are gated behind a paid plan, so it fails the no-card rule. A Gradio-only Space cannot run this FastAPI image.

**Koyeb.** Same size as Render, but a card is required for verification, so it fails the rule. It would otherwise be close: scale to zero after an hour is gentler than 15 minutes.

**Fly.io.** The trial is no-card but lasts 7 days and $1; the lasting free plan needs a card. Fails the rule for anything that must stay up.

**Railway.** No card, Docker works, but $1 a month of credit does not cover an always-on service, and it stops rather than sleeps when the credit runs out. Possible only as a demo that is allowed to go dark.

## Recommendation

**Render free web service**, with Vercel for web and Neon for Postgres kept. It is the only option that passes all three of: no card, runs our Docker image unchanged, and sleeps and wakes rather than stopping for the month. Accept the 15-minute spin-down and the roughly one-minute cold start.

The "waking up the server" state it implies: the web app calls `/readyz` on load; while the call is pending or fails it shows "waking up the server, about a minute" and retries with a short back-off, then shows the page. Neon scales to zero too, so the first `/readyz` after a long sleep may include the database wake as well; the state covers both. A scheduled ping to keep Render awake is not proposed: it would burn the 750 hours and treats a limit as a bug.

Before any deploy: measure the API's resident memory under a chat request (fits 512 MB or not), and time a cold start on 0.1 CPU. If memory does not fit, the next step is Koyeb with a card on file, which is the owner's call, or a smaller image.

## At 1000x the load

The free tier stops being the answer long before: one 0.1 CPU instance, no autoscaling, no worker. The container is plain and stateless, so the move is to any container platform (Cloud Run, Fly.io paid, Render paid) by changing deploy config, not code; that keeps the "portable" goal in the README. Next steps in order: a paid instance for the API, a separate worker service, a hosted model server and object storage.

## Read more

- [Render FAQ](https://render.com/docs/faq) (free spin-down, bandwidth suspension)
- [Hugging Face Spaces overview](https://huggingface.co/docs/hub/en/spaces-overview) (hardware, sleep time)
- [Koyeb pricing FAQ](https://www.koyeb.com/docs/faqs/pricing) and [instances](https://www.koyeb.com/docs/reference/instances)
- [Fly.io free trial](https://fly.io/docs/about/free-trial/) and [Railway free plan](https://docs.railway.com/pricing/free-plan)
