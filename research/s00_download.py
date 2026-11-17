"""Download FreshRetailNet-50K (Hugging Face, CC BY 4.0) into data/raw/, verified by size and SHA-256.

Standard library only, no account, no token. The commit is pinned so the files never drift.
The expected SHA-256 values are the LFS object ids that the Hugging Face tree API reports for each file.
Run from any directory:  python -I research/s00_download.py
"""
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
REPO = "Dingdong-Inc/FreshRetailNet-50K"
COMMIT = "c374e85975c82816c495acfa904cc55ab14a47d3"  # main as of the access date 2026-11-17
BASE = f"https://huggingface.co/datasets/{REPO}/resolve/{COMMIT}/"
TREE_API = f"https://huggingface.co/api/datasets/{REPO}/tree/{COMMIT}/data"
# (repository path, expected bytes, expected sha256 from the LFS object id)
FILES = [
    ("data/train.parquet", 106436287, "6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d"),
    ("data/eval.parquet", 8440124, "1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da10995e960e"),
]
CARD = "README.md"
UA = "research-script/1.0"


def fetch(url, dest):
    """Stream url into dest through a temporary name, then rename. Returns the byte count."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            total += len(block)
    tmp.replace(dest)
    return total


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = {"repo": REPO, "commit": COMMIT, "license": "CC-BY-4.0", "files": []}
    ok = True
    # Check the pinned tree still lists the same sizes and oids (read-only metadata call).
    req = urllib.request.Request(TREE_API, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        tree = {f["path"]: f for f in json.loads(resp.read().decode("utf-8"))}
    for rel, size, sha in FILES:
        meta = tree.get(rel)
        if meta is None or meta["lfs"]["size"] != size or meta["lfs"]["oid"] != sha:
            print(f"[tree] {rel}: listing differs from the pinned values; stop")
            return 1
    print("[tree] pinned sizes and oids match the Hugging Face listing")

    for rel, size, sha in FILES:
        dest = RAW / Path(rel).name
        if dest.exists() and dest.stat().st_size == size and sha256_of(dest) == sha:
            print(f"[skip] {dest.name}: already present and verified")
        else:
            n = fetch(BASE + rel, dest)
            print(f"[get ] {dest.name}: {n} bytes")
        got_size = dest.stat().st_size
        got_sha = sha256_of(dest)
        good = got_size == size and got_sha == sha
        ok = ok and good
        print(f"[check] {dest.name}: bytes {got_size} (expected {size}), sha256 {'match' if got_sha == sha else 'MISMATCH'}")
        manifest["files"].append({"path": f"data/raw/{dest.name}", "repo_path": rel, "bytes": got_size, "sha256": got_sha, "verified": good})

    card = RAW / "dataset_card_README.md"
    fetch(BASE + CARD, card)
    manifest["dataset_card"] = {"path": "data/raw/dataset_card_README.md", "bytes": card.stat().st_size, "sha256": sha256_of(card)}
    manifest["downloaded_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("[card] dataset_card_README.md saved")
    print("all files verified" if ok else "VERIFICATION FAILED")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
