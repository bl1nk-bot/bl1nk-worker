import os
import subprocess
import shutil
import json
import modal
from starlette.requests import Request
from starlette.responses import JSONResponse

app = modal.App("rust-builder")

image = (
    modal.Image.debian_slim()
    .apt_install("curl", "git", "build-essential", "clang", "jq")
    .run_commands(
        # Rust
        "curl https://sh.rustup.rs -sSf | sh -s -- -y",
        "bash -c 'source $HOME/.cargo/env && rustup default stable'",
        # Tools
        "bash -c 'source $HOME/.cargo/env && cargo install cargo-chef'",
        "bash -c 'source $HOME/.cargo/env && cargo install sccache'",
        # mold
        "curl -L https://github.com/rui314/mold/releases/download/v2.40.1/mold-2.40.1-x86_64-linux.tar.gz | tar xz",
        "cp mold-*/bin/mold /usr/local/bin/mold",
    )
)

cargo_registry = modal.Volume.from_name("cargo-registry", create_if_missing=True)
cargo_git = modal.Volume.from_name("cargo-git", create_if_missing=True)
sccache_volume = modal.Volume.from_name("sccache", create_if_missing=True)

# ------------------------------------------------------------
#  Build function – ใช้ภายใน, ไม่ใช่ endpoint โดยตรง
# ------------------------------------------------------------
@app.function(
    image=image,
    cpu=8,
    memory=16384,
    timeout=3600,
    volumes={
        "/root/.cargo/registry": cargo_registry,
        "/root/.cargo/git": cargo_git,
        "/sccache": sccache_volume,
    },
    env={
        "RUSTC_WRAPPER": "/root/.cargo/bin/sccache",
        "SCCACHE_DIR": "/sccache",
        "CARGO_HOME": "/root/.cargo",
    },
    secrets=[
        modal.Secret.from_name("github-token"),
        modal.Secret.from_name("webhook-secret"),   # สำหรับ auth
    ],
    concurrency_limit=3,          # ⚡ จำกัด container พร้อมกัน
)
async def build_impl(
    owner_repo: str,          # เช่น "owner/repo"
    sha: str,
    pr_number: str = None,
    create_release: bool = False,
):
    """Build Rust project, set GH status, label PR, optionally create release."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN in secrets")

    # ---------- 1. Clone (รองรับ private repo ด้วย token) ----------
    repo_api_base = f"https://api.github.com/repos/{owner_repo}"
    clone_url = f"https://x-access-token:{token}@github.com/{owner_repo}.git" if token else f"https://github.com/{owner_repo}.git"

    subprocess.run(["git", "clone", clone_url, "app"], check=True)
    os.chdir("app")
    subprocess.run(["git", "checkout", sha], check=True)

    # copy .cargo config (mold)
    builder_cargo_config = os.path.join(os.path.dirname(__file__), ".cargo")
    if os.path.isdir(builder_cargo_config):
        shutil.copytree(builder_cargo_config, ".cargo", dirs_exist_ok=True)

    # ---------- 2. Helper functions ----------
    def set_commit_status(state: str, description: str):
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"{repo_api_base}/statuses/{sha}",
            "-H", "Accept: application/vnd.github+json",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"state": state, "description": description, "context": "modal-build"})
        ], check=False)

    def add_pr_label(label: str):
        if not pr_number:
            return
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"{repo_api_base}/issues/{pr_number}/labels",
            "-H", "Accept: application/vnd.github+json",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"labels": [label]})
        ], check=False)

    def get_version_from_cargo():
        """ใช้ cargo metadata หา version ของ root package"""
        try:
            meta = subprocess.check_output(
                "bash -c 'source $HOME/.cargo/env && cargo metadata --format-version=1 --no-deps'",
                shell=True, text=True
            )
            pkg = json.loads(meta)
            # หา root package (ที่อยู่ใน workspace root หรือแยก)
            root = next((p for p in pkg["packages"] if p["id"] in pkg["resolve"]["root"]), None)
            if root:
                return root["version"]
        except Exception:
            pass
        return None

    def create_tag_and_release():
        """สร้าง git tag + GitHub release โดยดึง version จาก cargo metadata"""
        if not create_release:
            return
        version = get_version_from_cargo()
        if not version:
            print("⚠️  ไม่พบ version ใน Cargo.toml ข้ามการสร้าง release")
            return
        tag = f"v{version}"
        subprocess.run(["git", "tag", tag], check=True)
        subprocess.run(["git", "push", f"https://x-access-token:{token}@github.com/{owner_repo}.git", tag], check=True)
        subprocess.run([
            "curl", "-s", "-X", "POST",
            f"{repo_api_base}/releases",
            "-H", "Accept: application/vnd.github+json",
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"tag_name": tag, "name": tag, "body": "Automated release from Modal build"})
        ], check=True)

    # ---------- 3. Build + test ----------
    set_commit_status("pending", "Build started on Modal")

    try:
        subprocess.run(
            "bash -c 'source $HOME/.cargo/env && cargo chef prepare --recipe-path recipe.json'",
            shell=True, check=True
        )
        subprocess.run(
            "bash -c 'source $HOME/.cargo/env && cargo chef cook --release --recipe-path recipe.json'",
            shell=True, check=True
        )
        subprocess.run(
            "bash -c 'source $HOME/.cargo/env && cargo build --release'",
            shell=True, check=True
        )
        subprocess.run(
            "bash -c 'source $HOME/.cargo/env && cargo test'",
            shell=True, check=True
        )

        # Success
        set_commit_status("success", "Build & tests passed")
        add_pr_label("ready-to-merge")
        create_tag_and_release()

        subprocess.run(
            "bash -c 'source $HOME/.cargo/env && sccache --show-stats'",
            shell=True, check=True
        )
        return "OK"

    except subprocess.CalledProcessError:
        set_commit_status("failure", "Build or test failed")
        add_pr_label("build-failed")
        raise


# ------------------------------------------------------------
#  Webhook endpoints
# ------------------------------------------------------------
async def authenticate(request: Request):
    """ดึง secret จาก header เทียบกับ config"""
    expected = os.environ.get("WEBHOOK_SECRET", "")
    auth_header = request.headers.get("Authorization", "")
    # รูปแบบ: "Bearer <token>"
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    else:
        token = ""
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None  # auth passed

@app.web_endpoint(method="POST")
async def build_webhook(request: Request):
    """PR build endpoint – /build"""
    if auth_resp := await authenticate(request):
        return auth_resp
    data = await request.json()
    build_impl.spawn(
        data["owner_repo"],
        data["sha"],
        pr_number=data.get("pr_number"),
        create_release=False,
    )
    return {"ok": True, "type": "build"}

@app.web_endpoint(method="POST")
async def release_webhook(request: Request):
    """Release endpoint – /release"""
    if auth_resp := await authenticate(request):
        return auth_resp
    data = await request.json()
    build_impl.spawn(
        data["owner_repo"],
        data["sha"],
        pr_number=None,
        create_release=True,
    )
    return {"ok": True, "type": "release"}
