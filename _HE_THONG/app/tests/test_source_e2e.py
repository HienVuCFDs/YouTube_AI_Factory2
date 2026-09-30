"""From the "Thêm nguồn" box to Bước 1's analysis, one source kind all the way.

For each kind: detect → preview → import → the row's source_kind (what
Bước 1 reads from /api/videos) → the analyze step reads it as the right kind.
The network and the model are stood in for; everything between is the app's.
"""

from __future__ import annotations

import base64
import io
import unittest
import uuid
import wave
from unittest import mock

from fastapi.testclient import TestClient

from youtube_monitor import main, page_source
from youtube_monitor.source_links import describe

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _brief(topic: str) -> dict:
    return {"language": "vi", "content_type": "thử", "topic": topic, "content_summary": "Tóm tắt thử",
            "characters": [], "dialogue": [], "scene_map": [{"order": 1, "what_happens": "Một việc"}],
            "visual_style": "", "keywords": ["thử"], "limitations": []}


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.database = main.database
        self.sheet = mock.Mock(return_value=None)
        # The model is the one thing not run: it is handed what the app gathered.
        self.stack = [
            mock.patch.object(main, "_call_orchestrator_json", side_effect=lambda *a, **k: _brief("Nguồn thử")),
            mock.patch.object(main, "analysis_is_about_the_source", return_value=True),
            mock.patch.object(main, "_source_contact_sheet", self.sheet),
            mock.patch.object(main, "_sheet_from_remote_images", return_value=(None, 0)),
            mock.patch.object(main.database, "get_transcript", return_value={"content_text": "Xin chào, đây là lời nói."}),
        ]
        for patcher in self.stack:
            patcher.start()
            self.addCleanup(patcher.stop)

    def add_link(self, url: str) -> dict:
        preview = self.client.post("/api/sources/detect", json={"text": url}).json()
        added = self.client.post("/api/sources/import", json={"text": url})
        self.assertEqual(added.status_code, 200, added.text)
        return {"preview": preview, **added.json()}

    def analyse(self, video_id: str) -> dict:
        catalogue = {row["youtube_video_id"]: row for row in self.client.get("/api/videos?limit=500").json()}
        step1_sees = catalogue[video_id]["source_kind"]
        project = self.client.post(f"/api/videos/{video_id}/project", json={}).json()["project"]
        run = self.client.post(f"/api/projects/{project['id']}/steps/analyze", json={"options": {}})
        self.assertEqual(run.status_code, 200, run.text)
        body = run.json()["result"]
        saved = self.database.get_video_analysis(video_id, analysis_type="reference")
        return {"step1": step1_sees, "read_as": body["source"]["source_kind"],
                "brief": body["result"]["source_type"], "saved": saved["source_type"]}

    def check(self, found: dict, *, stored: str, read_as: str) -> None:
        self.assertEqual(found["step1"], stored, "Bước 1 is handed the stored kind")
        self.assertEqual((found["read_as"], found["brief"], found["saved"]), (read_as, read_as, read_as))

    def test_youtube(self) -> None:
        native, channel = "Y" + uuid.uuid4().hex[:10], "UC" + uuid.uuid4().hex[:22]
        url = f"https://www.youtube.com/watch?v={native}"
        info = {"id": native, "extractor_key": "Youtube", "title": "Video thử", "channel_id": channel,
                "channel": "Kênh", "duration": 62, "webpage_url": url}
        with mock.patch.object(main, "probe_source_link", return_value=describe(info, url)):
            added = self.add_link(url)
        self.assertEqual((added["preview"]["kind"], added["preview"]["source_kind"]), ("video", "video"))
        self.assertEqual(added["route"], "link_import")
        self.check(self.analyse(added["video"]["youtube_video_id"]), stored="video", read_as="video")
        self.sheet.assert_called()  # a video's frames are looked at

    def test_vnexpress(self) -> None:
        url = f"https://vnexpress.net/bai-thu-e2e-{uuid.uuid4().hex[:6]}-4800000.html"
        html = '<meta property="og:title" content="Bài thử"><meta property="og:site_name" content="VnExpress">'
        with mock.patch.object(page_source, "fetch_static", return_value=html), \
                mock.patch.object(main.web_research, "read_page", return_value="Nội dung bài viết thử, đủ dài để đọc."), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked")):
            added = self.add_link(url)
            self.assertEqual((added["preview"]["source_kind"], added["route"]), ("article", "page_import"))
            self.check(self.analyse(added["video"]["youtube_video_id"]), stored="article", read_as="article")

    def _listing(self, url: str, platform: str) -> None:
        product = {"name": "Sản phẩm thử", "read_status": "OK", "price": "119000", "currency": "VND",
                   "price_text": "119.000₫", "captured_at": "2026-09-30T06:00:00+00:00", "images": []}
        with mock.patch.object(page_source, "read_product", return_value=product), \
                mock.patch.object(page_source, "fetch_static", return_value="<title>Security Check</title>"), \
                mock.patch.object(main, "_withdraw_read_tasks", return_value=[]), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked")):
            added = self.add_link(url)
            self.assertEqual((added["preview"]["platform"], added["preview"]["source_kind"]), (platform, "product"))
            self.assertEqual(added["route"], "page_import")
            self.check(self.analyse(added["video"]["youtube_video_id"]), stored="product", read_as="product")

    def test_shopee(self) -> None:
        self._listing(f"https://shopee.vn/San-Pham-Thu-i.1.{uuid.uuid4().int % 10**9}", "shopee")

    def test_tiktok_shop(self) -> None:
        self._listing(f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}", "tiktok_shop")

    def test_a_set_of_pictures(self) -> None:
        found = self.client.post("/api/sources/detect-files", json={"files": [
            {"index": 0, "name": "a.png", "type": "image/png", "size": 10},
            {"index": 1, "name": "b.png", "type": "image/png", "size": 10},
        ]}).json()["sources"][0]
        self.assertEqual((found["kind"], found["source_kind"], found["route"]), ("image_collection", "image_collection", "image_collection"))
        created = self.client.post("/api/sources/image-collection", json={"title": "Bộ ảnh e2e"}).json()
        for name in ("a.png", "b.png"):
            upload = self.client.post(f"/api/projects/{created['project']['id']}/assets/upload", data={"asset_type": "image"},
                                      files={"file": (name, PNG + uuid.uuid4().bytes, "image/png")})
            self.assertEqual(upload.status_code, 200, upload.text)
        with mock.patch.object(main, "_contact_sheet_for_review", side_effect=lambda images, project_id: images[0]):
            self.check(self.analyse(created["video_id"]), stored="image_collection", read_as="images")

    def test_audio(self) -> None:
        found = self.client.post("/api/sources/detect-files", json={"files": [
            {"index": 0, "name": "giong.wav", "type": "audio/wav", "size": 10},
        ]}).json()["sources"][0]
        self.assertEqual((found["kind"], found["source_kind"], found["route"]), ("audio", "audio", "upload"))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(1)
            sound.setframerate(8000)
            sound.writeframes(uuid.uuid4().bytes * 250)
        upload = self.client.post("/api/uploads/source", files={"file": ("giong.wav", buffer.getvalue(), "audio/wav")})
        if upload.status_code == 400:
            self.skipTest(f"ffmpeg không đọc được file thử: {upload.json().get('detail')}")
        found = self.analyse(upload.json()["video"]["youtube_video_id"])
        self.check(found, stored="audio", read_as="audio")
        self.sheet.assert_not_called()  # a sound file has no frames to take


if __name__ == "__main__":
    unittest.main()
