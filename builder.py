import os
import re
import json
import subprocess
import shutil
import logging
from github import Github, GithubException
import modal
from starlette.requests import Request
from starlette.responses import JSONResponse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ────────────── Logging ──────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rust-builder")

# ────────────── Helper: run cargo commands ──────────────
def run_cargo_command(command: str):
    """Run a cargo command with proper environment setup."""
    full_cmd = f"bash -c 'source $HOME/.cargo/env && {command}'"
    logger.info(f"Running: {command}")
    subprocess.run(full_cmd, shell=True, check=True)


# ────────────── GitHub API Client ──────────────
class GitHubClient:
    def __init__(self, token: str):
        self.gh = Github(token)

    @retry(
        retry=retry_if_exception_type(GithubException),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    def set_commit_status(self, owner_repo: str, sha: str, state: str, description: str):
        logger.info(f"Setting commit status: {state} - {description}")
        repo = self.gh.get_repo(owner_repo)
        commit = repo.get_commit(sha)
        commit.create_status(state=state, description=description, context="modal-build")

    @retry(
        retry=retry_if_exception_type(GithubException),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    def add_pr_label(self, owner_repo: str, pr_number: str, label: str):
        if not pr_number:
            return
        logger.info(f"Adding label '{label}' to PR #{pr_number}")
        repo = self.gh.get_repo(owner_repo)
        issue = repo.get_issue(int(pr_number))
        issue.add_to_labels(label)

    @retry(
        retry=retry_if_exception_type(GithubException),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    def create_release(self, owner_repo: str, tag: str, body: str):
        logger.info(f"Creating release {tag}")
        repo = self.gh.get_repo(owner_repo)
        repo.create_git_release(tag_name=tag, name=tag, message=body)

    def tag_exists(self, owner_repo: str, tag: str) -> bool:
        repo = self.gh.get_repo(owner_repo)
        try:
            repo.get_git_ref(f"tags/{tag}")
            return True
        except GithubException as e:
            logger.warning(f"Tag check failed: {e.status} {e.data}")
            return False


# ────────────── Validation ──────────────
def validate_owner_repo(owner_repo: str):
    if not re.match(r"^[\w-]+/[\w.-]+$", owner_repo):
        raise ValueError(f"Invalid owner_repo: {owner_repo}")

def validate_sha(sha: str):
    if not re.match(r"^[0-9a-f]{7,40}$", sha):
        raise ValueError(f"Invalid sha: {sha}")


# ────────────── Build Pipeline ──────────────
class BuildPipeline:
    def __init__(self, owner_repo: str, sha: str, token: str, pr_number: str = None):
        validate_owner_repo(owner_repo)
        validate_sha(sha)
        self.owner_repo = owner_repo
        self.sha = sha
        self.token = token
        self.pr_number = pr_number
        self.gh = GitHubClient(token)

    def set_status(self, state: str, description: str):
        try:
            self.gh.set_commit_status(self.owner_repo, self.sha, state, description)
        except GithubException as e:
            logger.error(f"Failed to set status: {e.status} {e.data}")

    def add_label(self, label: str):
        try:
            self.gh.add_pr_label(self.owner_repo, self.pr_number, label)
        except GithubException as e:
            logger.error(f"Failed to add label: {e.status} {e.data}")

    def get_version_from_cargo_metadata(self):
        try:
            full_cmd = "bash -c 'source $HOME/.cargo/env && cargo metadata --format-version=1 --no-deps'"
            result = subprocess.check_output(full_cmd, shell=True, text=True)
            pkg = json.loads(result)
            root_id = pkg["resolve"]["root"]
            root = next((p for p in pkg["packages"] if p["id"] == root_id), None)
            return root["version"] if root else None
        except Exception as e:
            logger.error(f"Failed to read version: {e}")
            return None

    def clone_and_setup(self):
        if os.path.exists("app"):
            shutil.rmtree("app", ignore_errors=True)
        clone_url = f"https://x-access-token:{self.token}@github.com/{self.owner_repo}.git"
        subprocess.run(["git", "clone", clone_url, "app"], check=True)
        os.chdir("app")
        subprocess.run(["git", "checkout", self.sha], check=True)

        builder_cargo_config = os.path.join(os.path.dirname(__file__), ".cargo")
        if os.path.isdir(builder_cargo_config):
            shutil.copytree(builder_cargo_config, ".cargo", dirs_exist_ok=True)

    def build_and_test(self):
        run_cargo_command("cargo chef prepare --recipe-path recipe.json")
        run_cargo_command("cargo chef cook --release --recipe-path recipe.json")
        run_cargo_command("cargo build --release")
        run_cargo_command("cargo test")

    def create_release_if_needed(self, create_release: bool, tag: str = None):
        if not create_release:
            return
        if tag is None:
            version = self.get_version_from_cargo_metadata()
            if not version:
                logger.warning("No version found, skipping release")
                return
            tag = f"v{version}"
        if self.gh.tag_exists(self.owner_repo, tag):
            logger.info(f"Tag {tag} already exists, skipping release")
            return
        subprocess.run(["git", "tag", tag], check=True)
        subprocess.run(
            ["git", "push", f"https://x-access-token:{self.token}@github.com/{self.owner_repo}.git", tag],
            check=True
        )
        try:
            self.gh.create_release(self.owner_repo, tag, "Automated release from Modal build")
        except GithubException as e:
            logger.error(f"Failed to create release: {e.status} {e.data}")

    def run(self, create_release: bool = False, tag: str = None, dry_run: bool = False):
        if dry_run:
            logger.info("Dry-run mode: validating inputs only")
            return "DRY_RUN_OK"
        self.set_status("pending", "Build started on Modal")
        try:
            self.clone_and_setup()
            self.build_and_test()
            self.set_status("success", "Build & tests passed")
            if self.pr_number:
                self.add_label("ready-to-merge")
            self.create_release_if_needed(create_release, tag)
            return "OK"
        except subprocess.CalledProcessError:
            self.set_status("failure", "Build or test failed")
            if self.pr_number:
                self.add_label("build-failed")
            raise
        finally:
            try:
                run_cargo_command("sccache --show-stats")
            except Exception:
                pass
            # Commit volumes
            for vol in (cargo_registry, cargo_git, sccache_volume):
                if hasattr(vol, "commit"):
                    try:
                        vol.commit()
                    except Exception as e:
                        logger.warning(f"Volume commit failed: {e}")


# ────────────── Modal App Setup ──────────────
app = modal.App("rust-builder")

image = (
    modal.Image.debian_slim()
    .apt_install("curl", "git", "build-essential", "clang", "jq")
    .pip_install_from_requirements("requirements.txt")   # ✅ เพิ่ม Python deps ใน image
    .run_commands(
        "curl https://sh.rustup.rs -sSf | sh -s -- -y",
        "bash -c 'source $HOME/.cargo/env && rustup default stable'",
        "bash -c 'source $HOME/.cargo/env && cargo install cargo-chef'",
        "bash -c 'source $HOME/.cargo/env && cargo install sccache'",
        "curl -L https://github.com/rui314/mold/releases/download/v2.40.1/mold-2.40.1-x86_64-linux.tar.gz | tar xz",
        "cp mold-*/bin/mold /usr/local/bin/mold",
    )
)

cargo_registry = modal.Volume.from_name("cargo-registry", create_if_missing=True)
cargo_git = modal.Volume.from_name("cargo-git", create_if_missing=True)
sccache_volume = modal.Volume.from_name("sccache", create_if_missing=True)

build_env = {
    "RUSTC_WRAPPER": "/root/.cargo/bin/sccache",
    "SCCACHE_DIR": "/sccache",
    "CARGO_HOME": "/root/.cargo",
}
shared_secrets = [
    modal.Secret.from_name("github-token"),
    modal.Secret.from_name("webhook-secret"),
]
shared_volumes = {
    "/root/.cargo/registry": cargo_registry,
    "/root/.cargo/git": cargo_git,
    "/sccache": sccache_volume,
}

@app.function(
    image=image,
    cpu=8,
    memory=16384,
    timeout=3600,
    volumes=shared_volumes,
    env=build_env,
    secrets=shared_secrets,
    max_containers=3,
)
async def build_impl(
    owner_repo: str,
    sha: str,
    pr_number: str = None,
    create_release: bool = False,
    tag: str = None,
    dry_run: bool = False,
):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN in secrets")
    pipeline = BuildPipeline(owner_repo, sha, token, pr_number)
    return pipeline.run(create_release=create_release, tag=tag, dry_run=dry_run)


# ────────────── Auth ──────────────
async def authenticate(request: Request):
    expected = os.environ.get("WEBHOOK_SECRET", "")
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else ""
    if not expected or token != expected:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


# ────────────── Webhooks ──────────────
@app.web_endpoint(method="POST")
async def build_webhook(request: Request):
    if auth_resp := await authenticate(request):
        return auth_resp
    data = await request.json()
    build_impl.spawn(
        owner_repo=data["owner_repo"],
        sha=data["sha"],
        pr_number=data.get("pr_number"),
        create_release=False,
        dry_run=data.get("dry_run", False),
    )
    return {"ok": True, "type": "build"}

@app.web_endpoint(method="POST")
async def release_webhook(request: Request):
    if auth_resp := await authenticate(request):
        return auth_resp
    data = await request.json()
    build_impl.spawn(
        owner_repo=data["owner_repo"],
        sha=data["sha"],
        pr_number=None,
        create_release=True,
        tag=data.get("tag"),   # optional, from push tag
        dry_run=data.get("dry_run", False),
    )
    return {"ok": True, "type": "release"}