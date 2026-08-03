# Topic folders

Each child folder defines one content board used after the shared source fetch.

- `topic.json` controls the board name, order, color, threshold, and cadences.
- `match.md` defines what belongs in the board.
- `analysis.md` defines what the board considers valuable.
- `enrichment.md` defines what to preserve while expanding selected material.

Normal runs fetch the cadence's accounts once, then classify each article or post
into exactly one board from its own content. Source `category` values remain
account-management labels and do not determine the board. Daily runs combine the
`daily` and `x_watch` pools; weekly and reserve use their own pools.
