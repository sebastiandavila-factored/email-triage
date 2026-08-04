---
description: Run the local eval suite against the current prompt (Triage Studio)
---

Run the offline evaluation to sanity-check classification quality before publishing a
prompt change.

Steps:
1. Ensure `GROQ_API_KEY` is available in `.env` (the eval calls the real model).
2. Run the classification-only eval (faster, no LLM judge):

   ```bash
   make eval-quick
   ```

3. Report `accuracy`, `macro_f1`, and `ece` from the run. Compare against the last known
   baseline if the user has one.
4. If metrics look good, remind the owner they can publish via the Studio
   (`POST /workspaces/{tid}/prompt/publish`) — publishing runs its own eval-gate and
   freezes an immutable version. If metrics regressed, do NOT publish; investigate first.

Note: the offline dataset uses the legacy 5-category taxonomy. A per-tenant eval dataset
is future work — flag this if the workspace uses custom categories.
