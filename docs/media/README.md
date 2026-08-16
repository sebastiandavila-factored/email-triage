# Media checklist for the root README

Drop files here with these exact names and the placeholders in the root
`README.md` become live embeds (swap the blockquote placeholder for the
`![alt](docs/media/<file>)` / video embed noted next to each one).

| File | Status | What to capture |
|---|---|---|
| `demo.mp4` | ✅ done | Classify → confidence/draft → trace-debug agent explaining the decision. Converted from the source `.mov` (HEVC → H.264/AAC, faststart) for broad browser support. |
| `demo-thumb.png` | ✅ done | Frame pulled from the video at the "audit the decision" trace-debug beat. |
| `studio-ui.png` | ✅ done | Category editor for a real custom workspace taxonomy, with the published-version banner. Converted from HEIC. |
| `inbox.png` | ✅ done | Today's Gmail inbox auto-triaged — category chip, confidence, drafted reply per email. Converted from HEIC. |
| `logfire-metrics.png` | ✅ done | Web Server Metrics dashboard: total/avg duration and p95 by route, request volume. Converted from HEIC. |
| `logfire-costs.png` | ✅ done | LLM Tokens and Costs dashboard: input/output tokens and cost by model (added — not in the original list, but ties directly to the $9/mailbox economics claim). Converted from HEIC. |
| `eval-run.png` | ✅ done | `make eval` summary report: 91.5% accuracy (43/47), macro-F1 0.920, per-category P/R/F1, ECE 0.017, LLM judge 4.7/5, misclassified cases listed. Converted from HEIC. |
| `eval-cases.png` | ✅ done | Per-case `pydantic-evals` judge breakdown (relevance/tone/correctness/language match) — added, shows evaluator granularity beyond the aggregate report. Converted from HEIC. |

All 8 media files are in. Nothing left pending from the original checklist.
