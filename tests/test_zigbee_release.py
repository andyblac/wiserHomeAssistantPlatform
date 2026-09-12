"""Test Zigbee release selection and staging without network access."""
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("fetch_zigbee", Path(__file__).resolve().parents[1] / "scripts/fetch_zigbee_release.py")
FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)


def release(tag, date, prerelease=False, draft=False, asset=True):
    return {
        "tag_name": tag, "published_at": date, "prerelease": prerelease, "draft": draft,
        "assets": [{"id": 1, "name": "wiser-zigbee-card.js", "state": "uploaded", "size": 200,
                    "browser_download_url": f"https://github.com/andyblac/wiser-zigbee-card/releases/download/{tag}/wiser-zigbee-card.js"}] if asset else [],
    }


class ZigbeeReleaseTest(unittest.TestCase):
    def setUp(self):
        self.beta = release("v3-beta", "2026-09-01T00:00:00Z", True)
        self.stable = release("v2", "2026-09-02T00:00:00Z")
        self.releases = [self.stable, self.beta, release("draft", "2026-09-03T00:00:00Z", True, draft=True)]

    def test_dev_prefers_prerelease(self):
        self.assertEqual(FETCH.select_release(self.releases, "dev"), self.beta)

    def test_stable_excludes_prereleases_and_drafts(self):
        self.assertEqual(FETCH.select_release(self.releases, "stable"), self.stable)

    def test_dev_falls_back_to_stable(self):
        self.assertEqual(FETCH.select_release([self.stable], "dev"), self.stable)

    def test_stable_never_falls_back_to_beta(self):
        with self.assertRaises(ValueError):
            FETCH.select_release([self.beta], "stable")

    def test_missing_release_or_asset_fails(self):
        with self.assertRaises(ValueError):
            FETCH.select_release([], "dev")
        with self.assertRaises(ValueError):
            FETCH.select_asset(release("missing", "2026", asset=False), "wiser-zigbee-card.js")

    def test_plan_does_not_download_or_write(self):
        with TemporaryDirectory() as directory:
            out = Path(directory) / "not-created"
            with patch.object(FETCH, "list_releases", return_value=self.releases), patch.object(FETCH, "download_asset") as download:
                report = FETCH.fetch_zigbee("dev", out, FETCH.DEFAULT_REPOSITORY, plan=True)
            download.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(report["tag"], "v3-beta")

    def test_failed_download_preserves_existing_asset(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            target = out / "wiser-zigbee-card.js"
            target.write_bytes(b"original")
            with patch.object(FETCH, "list_releases", return_value=self.releases), patch.object(FETCH, "download_asset", side_effect=ValueError("failed")):
                with self.assertRaises(ValueError):
                    FETCH.fetch_zigbee("dev", out, FETCH.DEFAULT_REPOSITORY)
            self.assertEqual(target.read_bytes(), b"original")

    def test_download_updates_only_zigbee_and_records_provenance(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            untouched = out / "other-card.js"
            untouched.write_bytes(b"original")
            with patch.object(FETCH, "list_releases", return_value=self.releases), patch.object(FETCH, "download_asset", return_value=(b"new card", "sha256:test")):
                FETCH.fetch_zigbee("dev", out, FETCH.DEFAULT_REPOSITORY)
            self.assertEqual((out / "wiser-zigbee-card.js").read_bytes(), b"new card")
            self.assertEqual(untouched.read_bytes(), b"original")
            self.assertEqual(json.loads((out / "zigbee-release.json").read_text())["digest"], "sha256:test")
