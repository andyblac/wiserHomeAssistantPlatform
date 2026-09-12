"""Fetch the published Zigbee card asset for integration packaging (never branch source)."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_REPOSITORY = "andyblac/wiser-zigbee-card"


def list_releases(repository):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError(f"Invalid repository: {repository}")
    releases = []
    for page in range(1, 101):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "wiser-card-packager"}
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}",
            headers=headers,
        )
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise ValueError(f"Too many releases in {repository}")


def select_release(releases, channel):
    published = [r for r in releases if not r.get("draft") and r.get("published_at")]
    stable = [r for r in published if not r.get("prerelease")]
    beta = [r for r in published if r.get("prerelease")]
    candidates = (beta or stable) if channel == "dev" else stable
    if not candidates:
        raise ValueError(f"No published {'prerelease or stable' if channel == 'dev' else 'stable'} release available")
    return max(candidates, key=lambda r: r["published_at"])


def select_asset(release, filename):
    assets = [a for a in release.get("assets", []) if a["name"] == filename and a.get("state") == "uploaded"]
    if len(assets) != 1:
        raise ValueError(f"Release {release['tag_name']} must have one uploaded {filename} asset")
    return assets[0]


def download_asset(repository, asset):
    url = asset["browser_download_url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not parsed.path.startswith(f"/{repository}/releases/download/"):
        raise ValueError("Asset URL is not a GitHub release download for the selected repository")
    # Public assets do not require forwarding the API token through redirects.
    with urlopen(Request(url, headers={"User-Agent": "wiser-card-packager"}), timeout=60) as response:
        contents = response.read()
    if len(contents) != asset["size"] or len(contents) < 100:
        raise ValueError(f"Incorrect size for {asset['name']}")
    digest = "sha256:" + sha256(contents).hexdigest()
    if asset.get("digest") and asset["digest"] != digest:
        raise ValueError(f"Digest mismatch for {asset['name']}")
    if contents.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("Downloaded HTML instead of JavaScript")
    return contents, digest


def fetch_zigbee(channel, output_dir, repository, plan=False):
    release = select_release(list_releases(repository), channel)
    asset = select_asset(release, "wiser-zigbee-card.js")
    record = {
        "repository": repository, "tag": release["tag_name"],
        "prerelease": release["prerelease"], "asset": asset["name"],
        "asset_id": asset["id"], "url": asset["browser_download_url"],
    }
    if not plan:
        contents, digest = download_asset(repository, asset)
        record["digest"] = digest
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
            staged = Path(temporary) / asset["name"]
            staged.write_bytes(contents)
            staged.replace(output_dir / asset["name"])
        (output_dir / "zigbee-release.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=["dev", "stable"], required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("dist/wiser/frontend"))
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--plan", action="store_true", help="Show the selected release without downloading or writing files")
    args = parser.parse_args()
    try:
        report = fetch_zigbee(args.channel, args.output_dir, args.repository, args.plan)
    except Exception as error:
        parser.exit(1, f"Card release fetch failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
