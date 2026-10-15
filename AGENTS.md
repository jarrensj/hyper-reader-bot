# No personal information in the repo

Never commit personal information — email addresses, phone numbers, wallet addresses, or similar PII — anywhere: not in tracked files, commit messages, or PR titles/descriptions.

- Secrets and personal values (`TELEGRAM_BOT_TOKEN`, the chat IDs in `TELEGRAM_ALLOWED_CHATS`) belong only in local/untracked env files (`.env`) or the Railway service's variables. Never commit their real values.
- When creating or updating a `.env.example`, omit any variable whose value is personal information entirely — do not include it with a placeholder, and never copy real values from `.env`.
- Before committing, scan the diff for anything matching an email, phone number, wallet address, or bot token and remove it first. Public protocol contract addresses (like Papertrade's in the README) aren't personal and are fine.

# Commit & PR guidelines

- **One feature per PR — no coupling.** Each feature reviews, merges, and reverts independently. A
  change spanning two features is two PRs.
- **Follow-ups live in the code as `TODO` comments.** If a PR description notes a follow-up that is
  required or recommended (but out of scope for this PR), also leave a `TODO:` comment at the relevant
  spot in the code describing it, so it isn't forgotten while the PR stays one feature.
- **Each PR is complete, not half-plumbing** — the code *and* the command, config, or docs that make it
  usable *and* a working path. No dead code.
- **Chain PRs as necessary** - if someone can't review right away, chain off each other instead of waiting otherwise try to make each PR off latest origin main
- **Fill the PR template's Deployment Notes** — does a Railway variable need to be set or changed? Does
  the saved state in `/data/watchers.json` change shape? Does it need a manual `railway up`?
- **Keep PRs reviewable** — small enough to read in one sitting.
- **Plain commit messages — no AI-attribution trailers.** Subject + body only. Never append any AI/assistant attribution to a commit.
- **Graduate to review, don't merge** — open each PR for review (`gh pr ready`) and stack dependents on
  its branch
