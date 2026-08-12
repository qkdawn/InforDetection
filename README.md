# RSSHub + Horizon + n8n Local Deployment

This folder contains a local Docker Compose deployment for:

- RSSHub: always-on RSS generation service.
- Horizon API: staged fetch, score, filter, enrich, and report pipeline.
- n8n: daily orchestration at 09:00 and manual execution.
- Browserless: renders 1080 x 1440 Xiaohongshu-style report cards.

## Start RSSHub

```powershell
F:\InforDetection\start-rsshub.ps1
```

RSSHub will be available at:

```text
http://localhost:1200
```

Example feeds:

```text
http://localhost:1200/github/repos/DIYgod/RSSHub/releases
http://localhost:1200/v2ex/topics/hot
http://localhost:1200/hackernews/best
```

## Start The Full Stack

```powershell
cd F:\InforDetection
docker compose up -d
```

Service URLs:

```text
RSSHub:     http://localhost:1200
Horizon:    http://localhost:8090/healthz
n8n:        http://localhost:5678
```

The active n8n workflow is `游戏创意雷达（Horizon）`. It runs one shared source
pool for each cadence, then routes every fetched item by its own content:

```text
/fetch -> /score -> /filter -> /enrich -> /report
```

The workflow has three cadences. Daily runs combine the RSS daily pool and all X
accounts; the AI classifier then chooses one of six content boards for each item:

```text
Daily             90 RSS + 100 X   daily at 09:00   24-hour window
Weekly            130 sources      Sunday at 10:00  168-hour window
Reserve            80 sources      manual only      720-hour window
```

Content boards are configured under:

```text
F:\InforDetection\Horizon\topics\
```

Each board owns `topic.json`, `match.md`, `analysis.md`, and `enrichment.md`.
There are no account-to-board assignments: account categories remain provenance
metadata, while classification uses the title and content of each item.

`/report` writes a complete Markdown report plus a 3:4 image deck to:

```text
F:\InforDetection\output\game-inspiration-radar-<date>-<run-id>\
```

The Markdown keeps every selected creative lead. Each lead answers three
questions: what happened, what relationship is genuinely fresh, and what kind of
game-design question it may inspire. The image deck contains a cover, overview,
up to nine single-page lead cards, and a methodology card.

The v2 source catalog contains 300 RSS sources and 100 X discovery accounts.
All 190 daily sources enter the same fetch. Weekly and reserve sources use the
same content-classification process at their own cadence.

Inspect the current dynamic topic list:

```text
GET http://localhost:8090/topics?cadence=daily
```

## Replay One Previously Fetched Link

Import `n8n/workflows/horizon-single-link-replay.json` when an AI agent needs to
verify the production chain without fetching all sources again. The workflow
creates a fresh one-item run from an existing raw-stage URL, then executes:

```text
/replay -> /score -> /filter -> /research -> /enrich -> /report
```

It never copies the source run's score, research, enrichment, or images. The
last node returns an `ai_context` object containing the source item, stage trace,
research evidence, Chinese editorial artifact, report paths, and image-provider
success or failure details.

Manual execution uses the saved Marshall Islands example. AI agents can call the
inactive workflow through its webhook after activation:

```json
{
  "source_run_id": "run-20260809T030054Z-caefd0d7",
  "item_url": "https://x.com/archaeologymag/status/2086172238332809661"
}
```

## Generate A Single-Topic Psychology Brief

The `屏幕里的我们` pipeline accepts one digital-life topic, generates six competing
interpretations, selects the least obvious recognizable angle, writes a compact
editorial script, runs a chief-editor rewrite, and renders a 3-4 page Xiaohongshu
deck. This is an emotional observation workflow rather than a research or
psychology-education workflow.

```powershell
$body = @{
  topic = "为什么越重要的消息，越容易拖着不回？"
  context = "讨论这个问题，并解释背后可能的心理现象、运作机制和适用边界。不要诊断。"
  deliver_feishu = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8090/psychology-brief `
  -ContentType "application/json" `
  -Body $body
```

The response includes the emotional insight, reviewed 3-4 page script, Markdown
path, and rendered PNG paths. Set `deliver_feishu` to `true` only when the completed
deck should be sent to the configured Feishu chat.

An importable n8n workflow is available at:

```text
F:\InforDetection\n8n\workflows\psychology-brief.json
```

Its webhook accepts the same three fields at `/webhook/psychology-brief`.
The imported workflow always enables Feishu delivery after all cards render
successfully; direct API calls can still set `deliver_feishu` to `false` for previews.

## Run Horizon Directly

Model provider and model name are configured in the local runtime files:

```text
F:\InforDetection\Horizon\data\config.json
F:\InforDetection\Horizon\.env
```

Run once:

```powershell
F:\InforDetection\run-horizon.ps1 -Hours 24
```

Generated summaries are saved under:

```text
F:\InforDetection\Horizon\data\summaries
```

## Switch Horizon To A Cloud Model

Edit:

```text
F:\InforDetection\Horizon\.env
F:\InforDetection\Horizon\data\config.json
```

For example, OpenAI:

```json
"ai": {
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key_env": "OPENAI_API_KEY"
}
```

Then put the key in `.env`:

```text
OPENAI_API_KEY=sk-...
```

## Useful Commands

```powershell
cd F:\InforDetection
docker compose ps
docker compose logs -f rsshub
docker compose pull
docker compose up -d rsshub
docker compose run --rm horizon --hours 48
docker compose down
```
