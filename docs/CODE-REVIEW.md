# AI-assisted code review

Automated, convention-aware review on every pull request, powered by the official
[Claude Code GitHub Action](https://github.com/anthropics/claude-code-action)
(which is built on the Claude Agent SDK) driving a **repo-local skill** tailored to
email-triage.

## How it works

```
pull_request event
   └─ .github/workflows/code-review.yml       # the GitHub Action job
        └─ anthropics/claude-code-action@v1
             └─ /review-pr  (.claude/skills/review-pr/SKILL.md)
                  ├─ git diff origin/<base>...HEAD    # only the changed lines
                  ├─ gh api .../pulls/N/comments      # prior Claude findings
                  ├─ checks against CLAUDE.md conventions
                  └─ posts inline comments (new / still-unaddressed only)
```

- **Workflow:** [`.github/workflows/code-review.yml`](../.github/workflows/code-review.yml).
  Runs on `opened`, `synchronize`, `ready_for_review`, `reopened`; skips drafts;
  cancels superseded runs; 20-minute timeout.
- **Review logic:** [`.claude/skills/review-pr/SKILL.md`](../.claude/skills/review-pr/SKILL.md).
  Edit this file to change what the reviewer looks for — it already knows the
  Triage Studio category rules, the DI/async/HTTP-code contracts, the
  "tests never call Groq" rule, and the strict-pyright bar.
- **LLM provider:** [OpenRouter](https://openrouter.ai) via its Anthropic-compatible
  endpoint (`ANTHROPIC_BASE_URL=https://openrouter.ai/api`). No Anthropic Console
  account is needed for inference; the GitHub App is still required for posting to PRs.
- **Model:** `anthropic/claude-haiku-4.5` (OpenRouter slug, cheap smoke-test default).
  Bump to `anthropic/claude-sonnet-4.5` / the current opus slug in `claude_args` for
  real review quality. Verify exact slugs at <https://openrouter.ai/anthropic>.

## One-time setup (human)

The agent cannot do these — they need repo admin and touch secrets/accounts.

1. **Install the Claude GitHub App** on `sebastiandavila-factored/email-triage`:
   <https://github.com/apps/claude> (grant Contents, Issues, Pull requests). This is
   only for GitHub auth (posting comments) — it is independent of the LLM provider.
   Easiest path: run `/install-github-app` from `claude` locally in this repo.
2. **Add your OpenRouter key as a repository secret** named `OPENROUTER_API_KEY`
   (Settings → Secrets and variables → Actions → New repository secret). Create the
   key at <https://openrouter.ai/keys>. The workflow's `env` block wires it to
   `ANTHROPIC_AUTH_TOKEN` and sets `ANTHROPIC_API_KEY: ""` so requests route to
   OpenRouter, not Anthropic.
3. Merge the PR that adds these files. From then on, every PR gets reviewed.

To test: open a PR (or push a commit to an existing one) and watch Claude post
inline comments within a couple of minutes.

## Notes

- **Workflow must live on the default branch (`main`).** `claude-code-action`
  refuses to run on a PR whose workflow file differs from the version on `main`
  (a security guard against a PR editing the reviewer that reviews it). It logs
  *"Workflow validation failed… will begin working once you merge your PR"* and
  skips with a green check. Consequence: the PR that **introduces or edits**
  `code-review.yml` / `claude.yml` is **not** reviewed — merge it first, then
  normal PRs (that don't touch these files) get reviewed. The same rule is why
  `@claude` (an `issue_comment` event) only ever uses the `main` version.
- **Cost:** each run uses GitHub Actions minutes + Claude API tokens. Keep
  `CLAUDE.md` concise (it's read every run) and use `--max-turns` to cap work.
- **Fork PRs:** GitHub withholds secrets from fork-PR runs. This repo is private,
  so internal branch PRs are fine; reviews won't run on PRs from forks.
- **Local use:** run `/review-pr` inside `claude` in this repo to review your
  working changes before opening a PR (prints findings instead of posting them).
- **Alternatives considered:** the off-the-shelf `code-review@claude-code-plugins`
  plugin needs zero maintenance but doesn't know this repo's conventions; a fully
  custom `claude-agent-sdk` script gives more control (Logfire/eval integration) at
  the cost of owning the agent loop. We chose the Action + repo-local skill as the
  balance of low maintenance and repo-awareness.
