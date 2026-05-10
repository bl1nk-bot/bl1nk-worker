# 0.0.1 — Initial Modal Rust Builder

## Added

- Initial Modal-based remote Rust build system
- GitHub Actions webhook trigger flow
- Rust build pipeline using:
  - cargo-chef
  - sccache
  - mold linker
- Prebuilt Modal image
- cargo registry cache
- cargo git cache
- sccache cache volume
- GitHub PR build trigger
- Release workflow support
- Commit status updates
- PR labels:
  - ready-to-merge
  - build-failed
- GitHub release creation
- Private repository cloning support
- Webhook endpoints:
  - `/build`
  - `/release`

## Architecture

- GitHub Actions used as orchestration layer
- Modal used as remote compute/build worker
- Multi-repository support via webhook payload

---

# 0.0.2 — Security & Workflow Improvements

## Added

- Webhook authentication via bearer token
- Modal secret integration:
  - `github-token`
  - `webhook-secret`
- Branch filtering
- `paths-ignore` support
- Workflow concurrency cancellation
- Release flow separation from PR flow
- Concurrency limits inside Modal workers

## Improved

- GitHub workflow examples
- README deployment instructions
- Multi-repo reusable workflow design
- PR/release separation

## Fixed

- Public webhook exposure risk
- Release triggering on PR builds
- Missing private repo authentication

---

# 0.0.3 — Refactor & Production Structure

## Added

- `BuildPipeline` abstraction
- `GitHubClient` abstraction
- Validation helpers:
  - repository validation
  - SHA validation
- `examples/` workflow templates
- Structured repository layout
- Release duplicate tag checks
- Automatic cleanup of previous `app/` workspace
- Volume persistence commits

## Improved

- Refactored monolithic build logic into reusable classes
- Improved release handling
- Better README documentation
- Cleaner Modal app structure
- Reusable OSS-style project structure

## Renamed

- `modal.py` → `builder.py`

## Fixed

- Invalid async `await` usage on sync function
- Incorrect `cargo metadata` root package parsing
- Rebuild issues caused by stale workspace folders
- Duplicate release/tag failures

---

# 0.0.4 — Stability & Hardening Pass

## Added

- Better cache persistence handling
- Safer release checks
- Additional internal error handling
- Improved Modal volume management
- Better separation between:
  - transport layer
  - build logic
  - GitHub integration

## Improved

- Production-readiness
- Maintainability
- Reusability across repositories
- Repository onboarding flow
- Developer experience

## Notes

Current status:

- Production-capable
- Multi-repository ready
- Modal-native remote Rust CI
- Optimized for low-cost distributed builds
- Ready for real-world testing

Remaining future work:

- Artifact upload
- Structured logging
- Retry strategy
- Matrix builds
- Target directory incremental cache
- Dry-run mode

ใช่ครับ เราได้แก้ไขตามนั้นทั้งหมดในรอบนี้ และนี่คือ 0.0.5 สำหรับการเปลี่ยนแปลงล่าสุด:

---

# 0.0.5 — Retry, Logging, Dry-Run & Cleanup

Added

- Retry strategy สำหรับ GitHub API calls ผ่าน tenacity
    (retry exponential backoff เมื่อเกิด GithubException)
- Structured logging แทน print() (ใช้ built-in logging module)
- Dry-run mode ("dry_run": true ใน webhook payload)
    สำหรับตรวจสอบอินพุตโดยไม่รัน build จริง
- Tag-driven release workflow ใน examples/modal-release.yml
    (รันเมื่อ push tag v* แทนการ push main เปล่า)
- รองรับ tag parameter ใน /release webhook (ใช้ tag ที่ส่งมาโดยตรง)

Improved

- Volume commit logic สะอาดขึ้น ใช้ลูป for vol in (cargo_registry, cargo_git, sccache_volume) แทนการ iterate dictionary
- BuildPipeline ไม่มี hidden state _create_release — ส่ง create_release และ tag เป็น parameter โดยตรง
- Error handling ใน GitHubClient แสดง e.status และ e.data เมื่อเกิด GithubException
- Code quality: แยก retry/config ออกจาก business logic, เพิ่มความโปร่งใสในการทำงาน

Notes

- tenacity ถูกเพิ่มใน requirements.txt
- Changelog นี้ต่อเนื่องจาก 0.0.4 — ระบบตอนนี้มี retry, logging, dry-run และ release flow ที่แข็งแรงขึ้น
- ฟีเจอร์ artifact upload ยังคงเป็นงานในอนาคต

# 0.0.6 — Fix Deployment Dependencies

## Fixed
- Added missing Python dependencies in deploy workflow (`pip install -r requirements.txt` instead of `pip install modal`)
- Included `starlette` in `requirements.txt` to prevent `ModuleNotFoundError` during `modal deploy`
- Added `.pip_install_from_requirements("requirements.txt")` to Modal image to ensure runtime dependencies are present in containers
- Resolved `ModuleNotFoundError` for `github` and `starlette` during deployment

## Changed
- Updated `deploy.yml` to use `workflow_dispatch` alongside push trigger for manual deployment

# 0.0.7 — API Compatibility Update

## Changed
- Renamed deprecated `concurrency_limit` parameter to `max_containers` in `@app.function` (Modal API change 2025-02-24)
