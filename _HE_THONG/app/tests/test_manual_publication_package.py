"""Manual social posts need a real handoff, not merely a video link."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from youtube_monitor import main


class ManualPublicationPackageTests(unittest.TestCase):
    def test_the_package_contains_video_copy_and_destination_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "short.mp4"
            video.write_bytes(b"mp4-bytes")
            thumbnail = root / "thumb.jpg"
            thumbnail.write_bytes(b"jpeg-bytes")
            publication = {
                "id": 42,
                "project_id": 99,
                "platform": "tiktok",
                "local_file_path": str(video),
                "thumbnail_path": str(thumbnail),
                "title": "Tiêu đề Short",
                "description": "Mô tả đã duyệt",
                "tags": ["short", "demo"],
                "output_profile": "tiktok",
                "video_variant": "short",
                "scheduled_at": "2030-01-01T12:00:00+00:00",
            }
            channel = {"name": "Kênh TikTok chính", "channel_url": "https://tiktok.example/channel"}
            with patch.object(main, "PRODUCTION_ARTIFACT_DIR", root / "artifacts"):
                archive = main._build_manual_publication_package(publication, channel)

            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(set(package.namelist()), {
                    "video.mp4", "caption.txt", "metadata.json", "README.txt", "thumbnail.jpg",
                })
                self.assertIn("#short #demo", package.read("caption.txt").decode("utf-8"))
                metadata = json.loads(package.read("metadata.json"))
            self.assertEqual(metadata["destination"]["platform"], "tiktok")
            self.assertEqual(metadata["destination"]["channel_name"], "Kênh TikTok chính")

    def test_the_download_endpoint_is_registered(self) -> None:
        paths = {getattr(route, "path", "") for route in main.app.routes}
        self.assertIn("/api/publications/{publication_id}/manual-package", paths)

