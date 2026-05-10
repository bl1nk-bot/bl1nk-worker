# Rust Modal Builder (Production Ready)

Remote Rust CI/CD runner on Modal  
ใช้สำหรับ build, test, tag และ release โปรเจกต์ Rust โดยอัตโนมัติ

## ✨ Features

- 🔐 Webhook authentication
- ⚡ Fast build: sccache, cargo-chef, mold
- 📦 Caches: cargo registry, git, sccache
- 🧪 ใช้ `cargo metadata` อ่านเวอร์ชัน
- 🏷️ สร้าง label และ commit status บน PR
- 🚀 สร้าง tag + GitHub Release (รองรับ tag‑driven)
- 🔁 Retry GitHub API calls ด้วย tenacity
- 📋 Structured logging (logging module)
- 🧪 Dry‑run mode สำหรับทดสอบ
- 🧱 Clean code: BuildPipeline, GitHubClient
- 🔒 รองรับ private repo
- ⏳ Concurrency limit (3 builds พร้อมกัน)

## 🚀 Deploy บน Modal

1. **ติดตั้ง dependencies**
   ```bash
   pip install -r requirements.txt
   modal setup
   ```

2. **สร้าง Modal secrets**
   ```bash
   modal secret create github-token GITHUB_TOKEN=ghp_xxxx
   modal secret create webhook-secret WEBHOOK_SECRET=your_random_secret
   ```

3. **Deploy**
   ```bash
   modal deploy builder.py
   ```

4. **URL endpoints**
   - PR build: `https://<workspace>--rust-builder-build-webhook.modal.run`
   - Release: `https://<workspace>--rust-builder-release-webhook.modal.run`

## 🔗 ตั้งค่าใน GitHub Rust Project

1. เพิ่ม GitHub Secrets:

   | Secret Name | Value |
   |------------|-------|
   | `MODAL_BUILD_WEBHOOK_URL` | URL `/build` |
   | `MODAL_RELEASE_WEBHOOK_URL` | URL `/release` |
   | `MODAL_WEBHOOK_SECRET` | ค่าเดียวกับที่ตั้งใน Modal |

2. ก็อปไฟล์จาก `examples/` ไปไว้ใน `.github/workflows/` ของ repo:
   - `modal-build.yml` → `.github/workflows/modal-build.yml`
   - `modal-release.yml` → `.github/workflows/modal-release.yml`

3. Commit และ push

## 🧪 Dry‑Run Mode

เพิ่ม `"dry_run": true` ใน body ของ webhook เพื่อตรวจสอบความถูกต้องโดยไม่รัน build จริง (เหมาะสำหรับ debugging)

## 🏷️ Release Strategy

- หากใช้ workflow แบบ tag (`on push tags`) ระบบจะใช้ tag ที่ส่งมาเป็น release tag โดยตรง
- หากไม่ส่ง `tag` (เช่น workflow push main แบบเดิม) ระบบจะอ่าน version จาก Cargo.toml และสร้าง tag `v{version}` โดยอัตโนมัติ
- ถ้า tag นั้นมีอยู่แล้ว จะข้ามขั้นตอน release

## 📌 หมายเหตุ

- Private repo ต้องใช้ GitHub token ที่มีสิทธิ์อ่าน repo
- Retry ใน GitHub API ช่วยให้ทนต่อ network hiccup และ rate limit (ในระดับหนึ่ง)
- ไฟล์หลักคือ `builder.py` (ไม่ใช้ชื่อ `modal.py` เพื่อหลีกเลี่ยงชื่อชน)
