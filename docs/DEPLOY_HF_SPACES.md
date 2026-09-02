# Deploy: Hugging Face Spaces + GitHub Actions (zero cost, no GCP)

This is the no-billing path. The web app runs on a free HF Space; the
zero-LLM re-verification cycle runs as a scheduled GitHub Action that commits
`data/ledger.json` back to the repo (so the ledger's history is a public git
log). No Firestore, no Cloud Run, no card.

## 1. The web app on Hugging Face Spaces

The GitHub Action `.github/workflows/sync-to-hf-space.yml` pushes `master` to
the Space on every commit and injects the HF README frontmatter in CI (so the
GitHub README stays clean). You only do the one-time setup:

1. https://huggingface.co/new-space → **SDK: Docker**, blank template,
   visibility **Public**. Name it e.g. `promiseproof`.
2. In **this GitHub repo → Settings → Secrets and variables → Actions**:
   - **Secret** `HF_TOKEN` = a Hugging Face **write** token
     (https://huggingface.co/settings/tokens).
   - **Variable** `HF_SPACE` = `<your-hf-username>/promiseproof`.
   Or from the CLI:
   ```
   gh secret set HF_TOKEN --body "hf_xxx"
   gh variable set HF_SPACE --body "<you>/promiseproof"
   ```
3. In the **Space → Settings → Variables and secrets**:
   - **Secret** `NEBIUS_API_KEY` = the (rotated) Nebius Token Factory key. Only
     the live "test the pipeline" demo needs it; the scorecard, the chain and
     the MCP tools work without it.
4. Kick the first sync: `gh workflow run "sync to Hugging Face Space"` (or just
   push any commit). The Space builds the existing `Dockerfile`.

The `Dockerfile` binds the web app to `:8080` (`WEB_APP_PORT`/`PORT`), which is
why the injected frontmatter says `app_port: 8080` - no Space variable needed.
`LEDGER_BACKEND` defaults to `json`, so it serves the committed
`data/ledger.json` baseline; the MCP server runs on an internal port.

> HF Spaces' disk is ephemeral and the Space sleeps when idle. That's fine:
> writes there don't need to survive (the committed ledger is the source of
> truth), and the demo wakes on the first request. The *moving* scorecard
> comes from step 2, not from the Space.

## 2. The 6-hour cycle on GitHub Actions

Already committed: `.github/workflows/verify-cycle.yml`. It needs nothing set
up — `GITHUB_TOKEN` with `contents: write` (declared in the workflow) is
enough to push. To check it works now, run it once by hand:

```
gh workflow run "zero-LLM verification cycle"
gh run watch
```

Every 6 hours it: installs `requirements-cycle.txt` (just `pydantic` +
`httpx`), runs `python -m ledger.run_cycle --all`, asserts the hash chain is
intact, and commits `data/ledger.json` if any status changed. The Space picks
up the new baseline on its next rebuild/restart (or add a step to the workflow
that hits the Space's `POST /api/verify-cycle` to refresh it live).

## 3. What goes in the Devpost "Try it out" fields

- Code repo: `https://github.com/yobanrg6-coder/promiseproof`
- Live demo: `https://huggingface.co/spaces/<you>/promiseproof`
- The `/api/chain` endpoint and the git commit history of `data/ledger.json`
  are both worth pointing a judge at — that's the tamper-evidence, live.
