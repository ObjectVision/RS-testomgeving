import subprocess
from pathlib import Path
from urllib.parse import urlparse

def clone_gitrepo_sha1(git_repository_url: str, sha_1: str, projdir: str) -> str:
    """
    Clones a Git repository to a specific directory and checks out a specific commit SHA1.
    """
    if not git_repository_url or not sha_1 or not projdir:
        raise ValueError("URL, SHA1 and projdir must not be empty.")

    git_repository_url = git_repository_url.strip()
    sha_1 = sha_1.strip()

    parent_dir = Path(projdir).expanduser().resolve()
    parent_dir.mkdir(parents=True, exist_ok=True)

    repo_part = git_repository_url.rstrip("/")
    if repo_part.endswith(".git"):
        repo_part = repo_part[:-4]

    if "://" in repo_part:
        parsed = urlparse(repo_part)
        git_repository_name = Path(parsed.path).name
    else:
        git_repository_name = Path(repo_part.split(":")[-1]).name

    clone_dir = parent_dir / f"{git_repository_name}_{sha_1}"

    if not clone_dir.exists():
        def run_git(*args: str, cwd: Path | None = None):
            subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                check=True,
                text=True,
                capture_output=True,
            )

        run_git("clone", git_repository_url, str(clone_dir))
        run_git("checkout", sha_1, cwd=clone_dir)

    return str(clone_dir).replace("\\", "/")