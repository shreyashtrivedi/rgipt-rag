"""Deploy the chatbot to a free Hugging Face Space (Docker, CPU).

    .venv\\Scripts\\hf auth login                      # once; paste a *write* token from huggingface.co/settings/tokens
    .venv\\Scripts\\python deploy_hf.py <username>/<space-name>

Uploads only what the Docker image needs: code, frontend and the built index (chunks.jsonl +
chroma_db/), which git ignores. Hugging Face then builds the Dockerfile itself. Run it again
after re-running ingest.py to ship a new index.

The Gemini key is NOT uploaded: add it once in the Space's Settings -> "Variables and secrets"
as a secret named GEMINI_API_KEY.
"""
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parent
FILES = ["Dockerfile", "requirements.txt", "backend/*.py", "frontend/*",
         "data/processed/chunks.jsonl", "chroma_db/**"]

# Spaces read their settings from the front matter of the Space's README.md
SPACE_README = """---
title: RGIPT Assistant
emoji: 🛢️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
---

Question-answering chatbot for the RGIPT website (student project, not an official RGIPT
service). Answers come only from the public website content, with links to the sources.
"""


def main():
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("usage: python deploy_hf.py <username>/<space-name>")
    repo = sys.argv[1]
    if not (ROOT / "chroma_db").exists():
        sys.exit("No chroma_db/ -- run backend/ingest.py first.")

    api = HfApi()
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
    api.upload_file(path_or_fileobj=SPACE_README.encode(), path_in_repo="README.md",
                    repo_id=repo, repo_type="space")
    api.upload_folder(folder_path=ROOT, repo_id=repo, repo_type="space",
                      allow_patterns=FILES, ignore_patterns=["**/__pycache__/**"],
                      delete_patterns=["chroma_db/**"],   # drop index files from an older upload
                      commit_message="Deploy")
    user, name = repo.split("/")
    print(f"Uploaded. Build logs: https://huggingface.co/spaces/{repo}")
    print(f"When it's running:   https://{user}-{name}.hf.space".lower().replace("_", "-"))
    print("Remember: add the GEMINI_API_KEY secret in the Space's settings.")


if __name__ == "__main__":
    main()
