# Deploy: Hugging Face Spaces + GitHub Actions (zero cost, no GCP)

This is the no-billing path. The web app runs on a free HF Space; the
zero-LLM re-verification cycle runs as a scheduled GitHub Action that commits
`data/ledger.json` back to the repo (so the ledger's history is a public git
log). No Firestore, no Cloud Run, no card.

## 1. The web app on Hugging Face Spaces

1. https://huggingface.co/new-space → **SDK: Docker**, blank template,
   visibility **Public**.
2. In the Space, **Settings → Variables and secrets**:
   - Secret `NEBIUS_API_KEY` = the (rotated) Nebius Token Factory key. Only the
     live "test the pipeline" demo needs it; the scorecard, the chain and the
     MCP tools work without it.
   - Variable `WEB_APP_PORT` = `7860` (HF serves Docker Spaces on 7860).
3. Point the Space at this repo's code. Either:
   - **Push the repo to the Space's git remote** (`git remote add space
     https://huggingface.co/spaces/<you>/promiseproof` then `git push space
     master:main`), **or**
   - add the "Sync to Hugging Face" GitHub Action with an `HF_TOKEN` repo
     secret (HF's own template).
4. The Space's `README.md` needs this frontmatter at the very top (HF reads it;
   it's harmless on GitHub):

   ```yaml
   ---
   title: PromiseProof
   emoji: 📜
   colorFrom: green
   colorTo: gray
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

The existing `Dockerfile` already does the right thing: `run.py` binds the web
app to `0.0.0.0:$WEB_APP_PORT` (7860 here) and starts the MCP server on an
internal port. `LEDGER_BACKEND` defaults to `json`, so it serves the committed
`data/ledger.json` baseline.

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
