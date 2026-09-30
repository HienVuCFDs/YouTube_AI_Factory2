"""NGUỒN: detect, preview, then add through the importer that already existed.

The detector only decides the route. A channel goes to the channel sync, a
video or a page to the link importer, files to the upload and the project
assets - and adding the same thing twice does not make a second copy.
"""

from __future__ import annotations

import base64
import io
import json
import unittest
import uuid
import wave
from unittest import mock

from fastapi.testclient import TestClient

from youtube_monitor import main, page_source, platform_connections, source_brief
from youtube_monitor.source_links import SourceLinkError, describe

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _native() -> str:
    return "Y" + uuid.uuid4().hex[:10]


def _youtube_info(native: str, channel: str) -> dict:
    return {
        "id": native, "extractor_key": "Youtube", "title": f"Video {native}", "description": "Mô tả",
        "uploader": "Kênh thật", "channel": "Kênh thật", "channel_id": channel, "duration": 62,
        "thumbnail": f"https://i.ytimg.com/vi/{native}/hq.jpg", "webpage_url": f"https://www.youtube.com/watch?v={native}",
    }


class _Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._client_cm = TestClient(main.app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def setUp(self) -> None:
        self.database = main.database

    def listed(self, group: str = "all") -> dict:
        return {item["video_id"]: item for item in self.client.get(f"/api/sources?group={group}").json()["items"]}


class DetectEndpointTests(_Api):
    def test_the_first_answer_comes_from_the_link_alone(self) -> None:
        boom = AssertionError("network used")
        with mock.patch("httpx.get", side_effect=boom), mock.patch.object(main, "probe_source_link", side_effect=boom):
            body = self.client.post("/api/sources/detect", json={"text": "https://youtu.be/dQw4w9WgXcQ", "probe": False}).json()
        self.assertEqual((body["kind"], body["platform"], body["native_id"]), ("video", "youtube", "dQw4w9WgXcQ"))
        for field in ("kind", "platform", "native_id", "url", "title", "thumbnail", "metadata", "confidence", "suggested_action"):
            self.assertIn(field, body)

    def test_files_are_grouped_from_their_names_and_types(self) -> None:
        body = self.client.post("/api/sources/detect-files", json={"files": [
            {"index": 0, "name": "a.jpg", "type": "image/jpeg", "size": 10},
            {"index": 1, "name": "b.png", "type": "image/png", "size": 10},
            {"index": 2, "name": "c.mp4", "type": "video/mp4", "size": 10},
            {"index": 3, "name": "d.wav", "type": "audio/wav", "size": 10},
        ]}).json()
        self.assertEqual([item["kind"] for item in body["sources"]], ["image_collection", "video", "audio"])


class LinkImportTests(_Api):
    def test_a_youtube_link_is_one_row_and_one_source_however_often_it_is_added(self) -> None:
        native, channel = _native(), "UC" + uuid.uuid4().hex[:22]
        url = f"https://www.youtube.com/watch?v={native}"
        with mock.patch.object(main, "probe_source_link", return_value=describe(_youtube_info(native, channel), url)):
            first = self.client.post("/api/sources/import", json={"text": url}).json()
            second = self.client.post("/api/sources/import", json={"text": f"https://youtu.be/{native}"}).json()
        self.assertEqual(first["video"]["youtube_video_id"], native)
        self.assertEqual(second["video"]["youtube_video_id"], native)
        self.assertEqual(len(self.database.find_videos_by_native_id("youtube", native)), 1)
        item = self.listed()[native]
        self.assertEqual((item["kind"], item["group"], item["platform"]), ("video", "video", "youtube"))
        # Bước 1 chọn nguồn từ kho video: nguồn mới có ở đó.
        catalogue = {video["youtube_video_id"] for video in self.client.get("/api/videos?limit=500").json()}
        self.assertIn(native, catalogue)

    def test_a_video_the_monitor_already_has_is_marked_not_copied(self) -> None:
        native, channel = _native(), "UC" + uuid.uuid4().hex[:22]
        self.database.upsert_channel({"youtube_channel_id": channel, "channel_url": "x", "title": "Kênh theo dõi"})
        self.database.upsert_video({
            "youtube_video_id": native, "youtube_channel_id": channel, "title": "Từ monitor",
            "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": "h",
            "raw_payload": {"kind": "youtube#video"},
        })
        self.assertNotIn(native, self.listed(), "what the monitor found is not a source")
        url = f"https://www.youtube.com/watch?v={native}"
        with mock.patch.object(main, "probe_source_link", return_value=describe(_youtube_info(native, channel), url)):
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertTrue(result["reused_row"])
        self.assertEqual(len(self.database.find_videos_by_native_id("youtube", native)), 1)
        self.assertEqual(self.database.get_video(native)["title"], "Từ monitor", "the monitor's row is kept")
        self.assertIn(native, self.listed())

    def test_an_article_is_read_as_a_page_and_analysed_as_an_article(self) -> None:
        url = f"https://vnexpress.net/bai-thu-{uuid.uuid4().hex[:8]}-4800000.html"
        html = ('<meta property="og:title" content="Bài thử"><meta property="og:site_name" content="VnExpress">'
                '<meta property="og:image" content="https://i.vnecdn.net/a.jpg">')
        with mock.patch.object(page_source, "fetch_static", return_value=html), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked for an article")):
            detected = self.client.post("/api/sources/detect", json={"text": url}).json()
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual((detected["kind"], detected["title"]), ("article", "Bài thử"))
        video = self.database.get_video(result["video"]["youtube_video_id"])
        self.assertEqual(video["source_kind"], "article", "no description, still an article")
        item = self.listed("article")[video["youtube_video_id"]]
        self.assertEqual((item["kind"], item["site"]), ("article", "VnExpress"))

    def test_a_listing_is_read_once_and_keeps_its_price_with_the_time(self) -> None:
        url = f"https://shopee.vn/Binh-Giu-Nhiet-{uuid.uuid4().hex[:6]}-i.1.{uuid.uuid4().int % 10**9}"
        product = {"name": "Bình giữ nhiệt", "read_status": "OK", "price_text": "₫199.000", "seller": "Shop B",
                   "images": ["https://cf.shopee.vn/x.jpg"], "captured_at": "2026-09-30T05:00:00+00:00",
                   "route": "session:extension:coccoc", "attempts": ["extension:coccoc: OK"]}
        opened = mock.Mock()
        opened.read.side_effect = AssertionError("the marketplace was opened a second time")
        with mock.patch.object(page_source, "read_product", return_value=product), \
                mock.patch.object(page_source, "fetch_static", return_value="<title>Shopee Việt Nam</title>"), \
                mock.patch.object(platform_connections, "manager", return_value=opened), \
                mock.patch.object(main, "probe_source_link", side_effect=AssertionError("yt-dlp asked for a listing")):
            detected = self.client.post("/api/sources/detect", json={"text": url}).json()
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual(detected["metadata"]["price_text"], "₫199.000")
        self.assertNotIn("coccoc", json.dumps(detected))
        video = self.database.get_video(result["video"]["youtube_video_id"])
        self.assertEqual(video["title"], "Bình giữ nhiệt")
        self.assertEqual(video["source_kind"], "product")
        item = self.listed("product")[video["youtube_video_id"]]
        self.assertEqual((item["platform"], item["price_text"]), ("shopee", "₫199.000"))
        self.assertEqual(item["price_captured_at"], "2026-09-30T05:00:00+00:00")

    def test_what_the_preview_found_stored_is_marked_without_reading_it_again(self) -> None:
        native, channel = _native(), "UC" + uuid.uuid4().hex[:22]
        self.database.upsert_channel({"youtube_channel_id": channel, "channel_url": "x", "title": "Kênh"})
        self.database.upsert_video({"youtube_video_id": native, "youtube_channel_id": channel, "title": "Đã có",
                                    "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": "h"})
        url = f"https://youtu.be/{native}"
        with mock.patch.object(main, "probe_source_link", side_effect=AssertionError("read again")), \
                mock.patch.object(main, "_import_video_from_link", side_effect=AssertionError("imported again")):
            detected = self.client.post("/api/sources/detect", json={"text": url}).json()
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual(detected["existing"]["video_id"], native)
        self.assertEqual((result["status"], result["reused_row"], result["kind"]), ("exists", True, "video"))
        self.assertIn(native, self.listed("video"))

    def test_an_old_link_import_stays_on_its_row_even_without_a_preview(self) -> None:
        # Measured 30/09 on the real app: re-importing moved such a video onto
        # its real channel, leaving the old channel row empty in KÊNH.
        native, channel = _native(), "UC" + uuid.uuid4().hex[:22]
        synthetic, old = f"WEB-YOUTUBE-{uuid.uuid4().hex[:12]}", f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_channel({"youtube_channel_id": synthetic, "channel_url": "x", "title": "Kênh · Youtube"})
        self.database.upsert_video({"youtube_video_id": old, "youtube_channel_id": synthetic, "title": "Cũ",
                                    "video_url": f"https://www.youtube.com/watch?v={native}", "metadata_hash": "h"})
        self.database.set_video_source_identity(old, source_platform="youtube", native_video_id=native, native_channel_id=channel)
        with mock.patch.object(main, "_import_video_from_link", side_effect=AssertionError("imported again")):
            result = self.client.post("/api/sources/import", json={"text": f"https://youtu.be/{native}"}).json()
        self.assertEqual((result["status"], result["video"]["youtube_video_id"]), ("exists", old))
        self.assertEqual(self.database.get_video(old)["youtube_channel_id"], synthetic)

    def test_a_page_stored_under_an_older_key_is_reused_not_copied(self) -> None:
        # Imported before this change, through yt-dlp's catch-all, under its own key.
        url = f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}"
        old = f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_channel({"youtube_channel_id": f"WEB-HTML5-{old[4:14]}", "channel_url": "x", "title": "x"})
        self.database.upsert_video({"youtube_video_id": old, "youtube_channel_id": f"WEB-HTML5-{old[4:14]}",
                                    "video_url": url, "title": "Móc treo", "metadata_hash": "h"})
        product = {"name": "Móc treo", "read_status": "OK", "price_text": "₫ 11.899", "captured_at": "2026-09-30T06:46:07+00:00"}
        with mock.patch.object(page_source, "read_product", return_value=product), \
                mock.patch.object(main, "_import_video_from_link", side_effect=AssertionError("imported again")):
            detected = self.client.post("/api/sources/detect", json={"text": url}).json()
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual(detected["existing"]["video_id"], old)
        self.assertEqual((result["status"], result["video"]["youtube_video_id"]), ("exists", old))
        item = self.listed("product")[old]
        self.assertEqual((item["kind"], item["price_text"]), ("product", "₫ 11.899"))
        self.assertEqual(self.database.get_video(old)["youtube_channel_id"], f"WEB-HTML5-{old[4:14]}", "the old row is untouched")

    def test_a_stored_page_named_after_a_check_page_gets_the_real_name(self) -> None:
        url = f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}"
        old = f"web-{uuid.uuid4().hex[:16]}"
        self.database.upsert_channel({"youtube_channel_id": "site-shop.tiktok.com", "channel_url": "x", "title": "x"})
        self.database.upsert_video({"youtube_video_id": old, "youtube_channel_id": "site-shop.tiktok.com",
                                    "video_url": url, "title": "Security Check", "metadata_hash": "h"})
        product = {"name": "Móc treo 6 nhánh", "read_status": "OK", "price_text": "₫ 11.899"}
        with mock.patch.object(page_source, "read_product", return_value=product):
            self.client.post("/api/sources/detect", json={"text": url})
            result = self.client.post("/api/sources/import", json={"text": url}).json()
        self.assertEqual((result["status"], result["video"]["title"]), ("exists", "Móc treo 6 nhánh"))
        self.assertEqual(self.database.get_video(old)["source_kind"], "product")

    def test_a_listing_behind_a_sign_in_is_explained_not_failed(self) -> None:
        url = f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}"
        product = {"name": "", "read_status": "NEED_LOGIN", "read_detail": "profile:tiktok bị chặn",
                   "attempts": ["profile:tiktok: NEED_LOGIN"], "sessions": [{"id": "profile:tiktok"}]}
        with mock.patch.object(page_source, "read_product", return_value=product):
            detected = self.client.post("/api/sources/detect", json={"text": url}).json()
        self.assertEqual((detected["status"], detected["suggested_action"]), ("need_connection", "connect_platform"))
        self.assertIn("Công cụ & kết nối", detected["message"])
        text = json.dumps(detected, ensure_ascii=False)
        for private in ("attempts", "sessions", "profile:tiktok", "NEED_LOGIN"):
            self.assertNotIn(private, text)

    def test_what_cannot_be_added_is_refused_in_plain_words(self) -> None:
        for text in ("khong phai link", "https://www.tiktok.com/@abc", "https://www.youtube.com/playlist?list=PL1"):
            with self.subTest(text=text):
                response = self.client.post("/api/sources/import", json={"text": text})
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("ERROR", response.json()["detail"])

    def test_a_technical_failure_is_not_shown_raw(self) -> None:
        failure = SourceLinkError("Không đọc được video từ link: ERROR: [generic] Unsupported URL: https://x")
        with mock.patch.object(main, "probe_source_link", side_effect=failure), \
                mock.patch.object(main, "_probe_page_link", return_value=None):
            response = self.client.post("/api/sources/import", json={"text": "https://www.bilibili.com/video/BV1zz4y1"})
        self.assertEqual(response.status_code, 400)
        for technical in ("ERROR", "Unsupported", "[generic]"):
            self.assertNotIn(technical, response.json()["detail"])


class ChannelRouteTests(_Api):
    def test_a_followed_channel_is_opened_not_synced_again(self) -> None:
        channel = "UC" + uuid.uuid4().hex[:22]
        self.database.upsert_channel({"youtube_channel_id": channel, "channel_url": "x", "title": "Đã theo dõi"})
        with mock.patch.object(main.service, "add_channel", side_effect=AssertionError("synced again")):
            result = self.client.post("/api/sources/import", json={"text": channel}).json()
        self.assertEqual((result["status"], result["channel_id"]), ("exists", channel))

    def test_a_new_channel_goes_to_the_channel_sync_and_is_not_a_source(self) -> None:
        channel = "UC" + uuid.uuid4().hex[:22]

        def added(reference, group_name="", max_videos=None):
            self.database.upsert_channel({"youtube_channel_id": channel, "channel_url": "x", "title": "Kênh mới"})
            return {"channel_id": channel, "videos_new": 0}

        before = self.client.get("/api/sources").json()["counts"]["all"]
        with mock.patch.object(main.service, "add_channel", side_effect=added) as sync:
            result = self.client.post("/api/sources/import", json={"text": f"https://www.youtube.com/channel/{channel}"}).json()
        sync.assert_called_once()
        self.assertEqual((result["status"], result["channel_id"]), ("imported", channel))
        self.assertEqual(self.client.get("/api/sources").json()["counts"]["all"], before, "no source row for a channel")
        listed = {item["youtube_channel_id"] for item in self.client.get("/api/channels").json()}
        self.assertIn(channel, listed)


class SourceListTests(_Api):
    def test_the_list_holds_what_was_added_and_old_projects_still_open(self) -> None:
        suffix = uuid.uuid4().hex[:12]
        old = f"web-{suffix}"
        self.database.upsert_channel({"youtube_channel_id": f"site-{suffix}.test", "channel_url": "x", "title": "x"})
        self.database.upsert_video({
            "youtube_video_id": old, "youtube_channel_id": f"site-{suffix}.test", "title": "Bài cũ",
            "video_url": f"https://{suffix}.test/bai", "description": "Nội dung", "duration_seconds": 0,
            "metadata_hash": "h", "raw_payload": {"source": "link_import", "platform": "web"},
        })
        project_id = int(self.database.create_production_project(old, title="Dự án cũ")["id"])
        idea = self.database.create_idea_project("Một ý tưởng", title="Ý tưởng")
        self.database.save_video_analysis(old, {"summary": "x"}, analysis_type="reference")
        listed = self.listed()
        self.assertIn(old, listed, "a link imported before this change is still a source")
        self.assertEqual((listed[old]["kind"], listed[old]["project_id"]), ("article", project_id))
        self.assertTrue(listed[old]["analyzed"])
        self.assertNotIn(idea["youtube_video_id"], listed, "an idea is not a source")
        self.assertEqual(self.client.get(f"/api/projects/{project_id}").status_code, 200)
        body = self.client.get("/api/sources").json()
        counts = body["counts"]
        self.assertEqual(counts["all"], sum(counts[key] for key in ("video", "article", "product", "file")))
        for group in ("video", "article", "product", "file"):
            with self.subTest(group=group):
                items = self.client.get(f"/api/sources?group={group}").json()["items"]
                self.assertTrue(all(item["group"] == group for item in items))

    def test_pictures_become_one_source_the_analysis_reads_as_images(self) -> None:
        created = self.client.post("/api/sources/image-collection", json={"title": "Chuyến đi"}).json()
        project_id, video_id = int(created["project"]["id"]), created["video_id"]
        self.assertNotIn(video_id, self.listed(), "no picture has arrived yet")
        upload = self.client.post(
            f"/api/projects/{project_id}/assets/upload",
            data={"asset_type": "image"}, files={"file": (f"{uuid.uuid4().hex[:6]}.png", PNG + uuid.uuid4().bytes, "image/png")},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        item = self.listed("file")[video_id]
        self.assertEqual((item["kind"], item["image_count"]), ("image_collection", 1))
        self.assertTrue(item["thumbnail_url"].startswith("/api/assets/"))
        project = self.database.get_production_project(project_id)
        images = [asset for asset in self.database.list_project_assets(project_id) if asset["asset_type"] == "image"]
        self.assertEqual(self.database.get_video(video_id)["source_kind"], "image_collection")
        self.assertEqual(source_brief.detect_kind(project, self.database.get_video(video_id), images), "images")

    def test_the_same_file_uploaded_twice_is_one_source(self) -> None:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as sound:
            sound.setnchannels(1)
            sound.setsampwidth(1)
            sound.setframerate(8000)
            sound.writeframes(uuid.uuid4().bytes * 250)  # half a second, different every run
        data = buffer.getvalue()
        first = self.client.post("/api/uploads/source", files={"file": ("tieng.wav", data, "audio/wav")})
        if first.status_code == 400:
            self.skipTest(f"ffmpeg không đọc được file thử: {first.json().get('detail')}")
        second = self.client.post("/api/uploads/source", files={"file": ("tieng-lan-2.wav", data, "audio/wav")})
        self.assertEqual(second.json()["status"], "duplicate")
        video_id = first.json()["video"]["youtube_video_id"]
        self.assertEqual(second.json()["video"]["youtube_video_id"], video_id)
        item = self.listed("file")[video_id]
        self.assertEqual((item["kind"], item["platform"]), ("audio", "local"))


if __name__ == "__main__":
    unittest.main()
