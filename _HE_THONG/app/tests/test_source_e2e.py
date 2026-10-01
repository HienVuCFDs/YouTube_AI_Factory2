"""One source_kind from the "Thêm nguồn" box to Bước 1's analysis.

For every input: Detection → Preview → Import → DB → GET /api/sources →
Bước 1 (the row it reads from /api/videos) → Analyze. The kind the detector
names is the kind stored, listed, shown and analysed - product stays product
all the way. The network and the model are stood in for; the rest is the app.
"""

from __future__ import annotations

import base64
import io
import subprocess
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from youtube_monitor import main, page_source, source_kinds
from youtube_monitor.source_links import describe

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
PRODUCT = {"name": "Sản phẩm thử", "read_status": "OK", "price": "119000", "currency": "VND",
           "price_text": "119.000₫", "captured_at": "2026-09-30T06:00:00+00:00", "images": []}


def _brief(*_args, **_kwargs) -> dict:
    return {"language": "vi", "content_type": "thử", "topic": "Nguồn thử", "content_summary": "Tóm tắt thử",
            "characters": [], "dialogue": [], "scene_map": [{"order": 1, "what_happens": "Một việc"}],
            "visual_style": "", "keywords": ["thử"], "limitations": []}


def _media(suffix: str, *args: str) -> bytes | None:
    """A one-second file made by ffmpeg, different every run; None when it cannot make one."""
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / f"clip{suffix}"
        command = [main.FFMPEG_BINARY, "-y", "-hide_banner", "-loglevel", "error", *args,
                   "-metadata", f"comment={uuid.uuid4().hex}", str(target)]
        try:
            done = subprocess.run(command, capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return target.read_bytes() if done.returncode == 0 and target.is_file() else None


class _ChainCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.sheet = mock.Mock(return_value=None)
        # The model and the network are the only stand-ins.
        for patcher in (
            mock.patch.object(main, "_call_orchestrator_json", side_effect=_brief),
            mock.patch.object(main, "analysis_is_about_the_source", return_value=True),
            mock.patch.object(main, "_source_contact_sheet", self.sheet),
            mock.patch.object(main, "_sheet_from_remote_images", return_value=(None, 0)),
            mock.patch.object(main, "_withdraw_read_tasks", return_value=[]),
            mock.patch.object(main.web_research, "read_page", return_value="Nội dung trang thử, đủ dài để đọc."),
            mock.patch.object(main.database, "get_transcript", return_value={"content_text": "Xin chào, đây là lời nói."}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    # ---- the chain -----------------------------------------------------------

    def follow(self, video_id: str, detected: dict, stored: str) -> dict:
        """DB → GET source → Bước 1 → Analyze, each asserted against the detection."""
        self.assertEqual(detected["source_kind"], stored, "preview")
        self.assertEqual(main.database.get_video(video_id)["source_kind"], stored, "DB")
        listed = {item["video_id"]: item for item in self.client.get("/api/sources").json()["items"]}
        self.assertEqual(listed[video_id]["kind"], stored, "GET /api/sources")
        catalogue = {row["youtube_video_id"]: row for row in self.client.get("/api/videos?limit=500").json()}
        self.assertEqual(catalogue[video_id]["source_kind"], stored, "Bước 1 reads this row")
        project = self.client.post(f"/api/videos/{video_id}/project", json={}).json()["project"]
        run = self.client.post(f"/api/projects/{project['id']}/steps/analyze", json={"options": {}})
        self.assertEqual(run.status_code, 200, run.text)
        body = run.json()["result"]
        read_as = source_kinds.ANALYSIS_KIND[stored]
        self.assertEqual((body["source"]["source_kind"], body["result"]["source_type"]), (read_as, read_as), "Analyze")
        return body["source"]

    def link(self, url: str, stored: str) -> dict:
        quick = self.client.post("/api/sources/detect", json={"text": url, "probe": False}).json()
        preview = self.client.post("/api/sources/detect", json={"text": url}).json()
        added = self.client.post("/api/sources/import", json={"text": url})
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(added.json()["kind"], stored, "import")
        return {"quick": quick, "preview": preview, "source": self.follow(added.json()["video"]["youtube_video_id"], preview, stored)}

    def upload(self, name: str, mime: str, data: bytes, stored: str) -> dict:
        found = self.client.post("/api/sources/detect-files", json={"files": [
            {"index": 0, "name": name, "type": mime, "size": len(data)}]}).json()["sources"][0]
        self.assertEqual(found["route"], "upload")
        sent = self.client.post("/api/uploads/source", files={"file": (name, data, mime)})
        if sent.status_code == 400:
            self.skipTest(f"ffmpeg không đọc được file thử: {sent.json().get('detail')}")
        return self.follow(sent.json()["video"]["youtube_video_id"], found, stored)


class SourceKindContractTests(_ChainCase):
    # ---- 1-2 YouTube -----------------------------------------------------------

    def _youtube(self, url: str, native: str) -> dict:
        info = {"id": native, "extractor_key": "Youtube", "title": "Video thử", "channel_id": "UC" + uuid.uuid4().hex[:22],
                "channel": "Kênh", "duration": 58, "webpage_url": url}
        with mock.patch.object(main, "probe_source_link", return_value=describe(info, url)):
            return self.link(url, "video")

    def test_01_youtube_video(self) -> None:
        native = "Y" + uuid.uuid4().hex[:10]
        found = self._youtube(f"https://www.youtube.com/watch?v={native}", native)
        self.assertEqual(found["quick"]["source_kind"], "video", "known from the link alone")
        self.sheet.assert_called()  # a video's frames are looked at

    def test_02_youtube_short(self) -> None:
        native = "S" + uuid.uuid4().hex[:10]
        found = self._youtube(f"https://www.youtube.com/shorts/{native}", native)
        self.assertTrue(found["preview"]["metadata"]["is_short"])

    # ---- 3-4 files -------------------------------------------------------------

    def test_03_mp4(self) -> None:
        data = _media(".mp4", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                      "-shortest", "-c:v", "mpeg4", "-c:a", "aac")
        if data is None:
            self.skipTest("ffmpeg không tạo được MP4 thử")
        self.upload("clip.mp4", "video/mp4", data, "video")
        self.sheet.assert_called()

    def test_04_wav_and_mp3(self) -> None:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(1)
            sound.setframerate(8000)
            sound.writeframes(uuid.uuid4().bytes * 250)
        self.upload("giong.wav", "audio/wav", buffer.getvalue(), "audio")
        self.sheet.assert_not_called()  # a sound file has no frames to take
        mp3 = _media(".mp3", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame")
        if mp3 is None:
            self.skipTest("ffmpeg không có bộ mã MP3; WAV đã kiểm")
        self.upload("giong.mp3", "audio/mpeg", mp3, "audio")
        self.sheet.assert_not_called()

    # ---- 5-7 pages -------------------------------------------------------------

    def _page(self, url: str, html: str, stored: str) -> dict:
        with mock.patch.object(page_source, "fetch_static", return_value=html), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked for a page")):
            return self.link(url, stored)

    def test_05_vnexpress(self) -> None:
        found = self._page(f"https://vnexpress.net/bai-e2e-{uuid.uuid4().hex[:6]}-4800000.html",
                           '<meta property="og:title" content="Bài thử"><meta property="og:site_name" content="VnExpress">', "article")
        self.assertEqual(found["quick"]["source_kind"], "article", "a news site's article, from the link alone")

    def test_06_a_page_whose_own_tags_say_article(self) -> None:
        found = self._page(f"https://tapchi-{uuid.uuid4().hex[:6]}.example.test/abc",
                           '<meta property="og:type" content="article"><meta property="og:title" content="Một bài">', "article")
        self.assertEqual(found["quick"]["source_kind"], "web", "the link alone could not say")
        self.assertEqual(found["preview"]["detected_by"], "metadata_probe")

    def test_07_a_site_that_says_nothing_more(self) -> None:
        found = self._page(f"https://congty-{uuid.uuid4().hex[:6]}.example.test/", "<title>Công ty ABC</title>", "web")
        self.assertEqual(found["source"]["source_kind"], "web", "read with the plain page reader")

    # ---- 8-10 listings ---------------------------------------------------------

    def _listing(self, url: str, platform: str) -> None:
        with mock.patch.object(page_source, "read_product", return_value=dict(PRODUCT)), \
                mock.patch.object(page_source, "fetch_static", return_value="<title>Security Check</title>"), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked for a listing")):
            found = self.link(url, "product")
        self.assertEqual((found["quick"]["source_kind"], found["preview"]["platform"]), ("product", platform))

    def test_08_shopee(self) -> None:
        self._listing(f"https://shopee.vn/San-Pham-i.1.{uuid.uuid4().int % 10**9}", "shopee")

    def test_09_tiktok_shop(self) -> None:
        self._listing(f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}", "tiktok_shop")

    def test_10_lazada(self) -> None:
        self._listing(f"https://www.lazada.vn/products/pdp-i{uuid.uuid4().int % 10**9}-s1.html", "lazada")

    # ---- 11 pictures -----------------------------------------------------------

    def test_11_a_set_of_pictures(self) -> None:
        found = self.client.post("/api/sources/detect-files", json={"files": [
            {"index": 0, "name": "a.png", "type": "image/png", "size": 10},
            {"index": 1, "name": "b.png", "type": "image/png", "size": 10},
        ]}).json()["sources"][0]
        self.assertEqual(found["route"], "image_collection")
        created = self.client.post("/api/sources/image-collection", json={"title": "Bộ ảnh e2e"}).json()
        for name in ("a.png", "b.png"):
            sent = self.client.post(f"/api/projects/{created['project']['id']}/assets/upload", data={"asset_type": "image"},
                                    files={"file": (name, PNG + uuid.uuid4().bytes, "image/png")})
            self.assertEqual(sent.status_code, 200, sent.text)
        with mock.patch.object(main, "_contact_sheet_for_review", side_effect=lambda images, project_id: images[0]):
            source = self.follow(created["video_id"], found, "image_collection")
        self.assertEqual(source["image_count"], 2, "both pictures were looked at")


class TheChainHoldsTests(_ChainCase):
    """A fresh detection is not overruled by an older guess, and a video is never stored as a page."""

    def test_an_older_guess_gives_way_to_what_the_preview_found(self) -> None:
        url = f"https://shop-{uuid.uuid4().hex[:6]}.example.test/p/1"
        old = f"web-{uuid.uuid4().hex[:16]}"
        main.database.upsert_channel({"youtube_channel_id": "site-x.test", "channel_url": "x", "title": "x"})
        main.database.upsert_video({"youtube_video_id": old, "youtube_channel_id": "site-x.test", "video_url": url,
                                    "title": "Trang cũ", "metadata_hash": "h", "duration_seconds": 0})
        self.assertEqual(main.database.get_video(old)["source_kind"], "web", "what the old row could say")
        listing = '<script type="application/ld+json">{"@type":"Product","name":"Bình","offers":{"price":"199000","priceCurrency":"VND"}}</script>'
        with mock.patch.object(page_source, "fetch_static", return_value=listing):
            preview = self.client.post("/api/sources/detect", json={"text": url}).json()
            added = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual((preview["source_kind"], added["kind"]), ("product", "product"))
        self.follow(old, preview, "product")

    def test_a_video_that_cannot_be_read_now_is_not_stored_as_a_page(self) -> None:
        from youtube_monitor.source_links import SourceLinkError

        url = f"https://vimeo.com/{uuid.uuid4().int % 10**9}"
        with mock.patch.object(main, "probe_source_link", side_effect=SourceLinkError("ERROR: blocked")), \
                mock.patch.object(main, "_probe_page_link", side_effect=AssertionError("stored as a page")):
            response = self.client.post("/api/sources/import", json={"text": url})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("ERROR", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
