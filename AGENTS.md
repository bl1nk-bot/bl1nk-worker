# bl1nk-worker

Modal-hosted remote Rust CI/CD worker. Receives webhooks from GitHub Actions, builds/tests Rust projects on Modal, reports commit statuses and PR labels, and optionally creates GitHub releases.

## Architecture

- Single entrypoint: `builder.py` — a Modal app with two webhook endpoints (`/build`, `/release`)
- Named `builder.py` (not `modal.py`) to avoid import collision with the `modal` package
- Consumer repos send webhooks via `.github/workflows/` templates in `examples/`
- Two Modal secrets required: `github-token`, `webhook-secret`

## Deploy

```bash
pip install -r requirements.txt
modal deploy builder.py
```

Only `builder.py`, `requirements.txt`, and `.cargo/config.toml` trigger redeployment (see `.github/workflows/deploy.yml`).

## Webhook endpoints

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `POST /build` | PR build + test | Bearer token (webhook-secret) |
| `POST /release` | Build + tag + GitHub Release | Bearer token (webhook-secret) |

Add `"dry_run": true` to the JSON body to validate inputs without executing.

## Build pipeline

Clone → `cargo chef prepare` → `cargo chef cook --release` → `cargo build --release` → `cargo test`

Caching: three Modal volumes (`cargo-registry`, `cargo-git`, `sccache`) committed at pipeline end. `.cargo/config` (mold linker via clang) is copied into the cloned repo.

## Conventions

- `@app.function` uses `max_containers=3` (not the deprecated `concurrency_limit`)
- PR builds auto-label `ready-to-merge` on success, `build-failed` on failure
- Release checks `tag_exists` before creating tags/releases
- Auth uses constant-time HMAC compare via `hmac.compare_digest`
