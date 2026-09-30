"""One detector for the "Thêm nguồn" box: links by their shape first, files by
their type, then what the source says about itself - never a model.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from youtube_monitor import page_source, platform_connections, source_detector as detector
from youtube_monitor.database import Database
from youtube_monitor.source_links import SourceLinkError
from youtube_monitor.youtube_client import YouTubeApiError

EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"},
    "audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"},
}


def _no_network():
    """Anything that would leave the machine fails the test."""
    stack = contextlib.ExitStack()
    boom = AssertionError("network used")
    stack.enter_context(mock.patch("httpx.get", side_effect=boom))
    stack.enter_context(mock.patch("httpx.Client.send", side_effect=boom))
    stack.enter_context(mock.patch("yt_dlp.YoutubeDL.YoutubeDL.extract_info", side_effect=boom))
    return stack


class UrlShapeTests(unittest.TestCase):
    CASES = [
        # text, kind, platform, native id
        ("https://www.youtube.com/@VuiVe", "youtube_channel", "youtube", ""),
        ("youtube.com/@VuiVe/videos", "youtube_channel", "youtube", ""),
        ("https://www.youtube.com/channel/UCw0YZ5HG7zOJsV3ZMRZZwvA", "youtube_channel", "youtube", "UCw0YZ5HG7zOJsV3ZMRZZwvA"),
        ("UCw0YZ5HG7zOJsV3ZMRZZwvA", "youtube_channel", "youtube", "UCw0YZ5HG7zOJsV3ZMRZZwvA"),
        ("@VuiVe", "youtube_channel", "youtube", ""),
        ("https://www.youtube.com/user/GoogleDevelopers", "youtube_channel", "youtube", ""),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1", "video", "youtube", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "video", "youtube", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "video", "youtube", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/playlist?list=PL123", "unsupported", "youtube", ""),
        ("https://www.tiktok.com/@vtv24news/video/7300000000000000000?lang=vi", "video", "tiktok", "7300000000000000000"),
        ("https://vt.tiktok.com/ZSabc123/", "video", "tiktok", ""),
        ("https://www.tiktok.com/@vtv24news", "channel", "tiktok", ""),
        ("https://shopee.vn/Tai-Nghe-S10-Mau-Den-Mini-Khong-Day-i.196261835.29134843988", "product", "shopee", "196261835:29134843988"),
        ("https://shop.tiktok.com/vn/pdp/1729384756123456789", "product", "tiktok_shop", "1729384756123456789"),
        ("https://www.lazada.vn/products/pdp-i204631671-s254952397.html", "product", "lazada", "204631671:254952397"),
        ("https://vnexpress.net/gia-vang-hom-nay-tang-manh-4800000.html", "article", "web", ""),
        ("https://vnexpress.net/kinh-doanh", "web", "web", ""),
        ("https://www.bilibili.com/video/BV1xx411c7mD", "video", "bilibili", ""),
        ("https://blog.example.com/posts/my-trip-to-hanoi", "article", "web", ""),
        ("https://example.com/", "web", "web", ""),
        ("not a url", "invalid", "", ""),
        ("", "invalid", "", ""),
    ]

    def test_every_shape_is_known_without_the_network(self) -> None:
        with _no_network():
            for text, kind, platform, native in self.CASES:
                with self.subTest(text=text):
                    found = detector.classify(text)
                    self.assertEqual(found["kind"], kind)
                    self.assertEqual(found["platform"], platform)
                    self.assertEqual(found["native_id"], native)

    def test_shorts_are_marked_and_links_are_made_canonical(self) -> None:
        short = detector.classify("https://youtube.com/shorts/dQw4w9WgXcQ?feature=share")
        self.assertTrue(short["metadata"]["is_short"])
        self.assertEqual(short["url"], "https://www.youtube.com/shorts/dQw4w9WgXcQ")
        self.assertEqual(detector.classify("youtu.be/dQw4w9WgXcQ")["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_what_cannot_be_added_says_so_plainly(self) -> None:
        for text in ("not a url", "https://www.youtube.com/playlist?list=PL1", "https://www.tiktok.com/@a"):
            with self.subTest(text=text):
                found = detector.classify(text)
                self.assertEqual(found["suggested_action"], "none")
                self.assertTrue(found["message"])
                for technical in ("ERROR", "Exception", "extractor", "HTTP"):
                    self.assertNotIn(technical, found["message"])

    def test_a_product_is_named_from_its_own_url(self) -> None:
        found = detector.classify("https://tiki.vn/may-loc-khong-khi-p123456.html")
        self.assertEqual(found["kind"], "product")
        self.assertEqual(found["title"], "may loc khong khi")

    def test_yt_dlp_is_asked_offline_for_sites_the_rules_do_not_know(self) -> None:
        with _no_network():
            self.assertEqual(detector.ytdlp_extractor("https://vimeo.com/76979871").lower(), "vimeo")
            self.assertEqual(detector.ytdlp_extractor("https://example.com/about"), "")
        profile = detector.classify("https://example.com/u/1", extractor_of=lambda url: "VimeoUser")
        self.assertEqual(profile["kind"], "channel")


class FileTests(unittest.TestCase):
    def detect(self, files, max_bytes=10**9):
        return detector.detect_files(files, extensions=EXTENSIONS, max_bytes=max_bytes)

    def test_each_file_type(self) -> None:
        cases = [
            ({"name": "a.JPG", "type": "image/jpeg", "size": 10}, "image"),
            ({"name": "b.png", "type": "image/png", "size": 10}, "image"),
            ({"name": "c.mp4", "type": "video/mp4", "size": 10}, "video"),
            ({"name": "d.mp3", "type": "audio/mpeg", "size": 10}, "audio"),
            ({"name": "e.wav", "type": "audio/wav", "size": 10}, "audio"),
            ({"name": "f.mkv", "type": "", "size": 10}, "video"),  # no MIME: the extension decides
            ({"name": "g.webm", "type": "audio/webm", "size": 10}, "video"),  # the importer takes .webm as video
        ]
        for item, kind in cases:
            with self.subTest(name=item["name"]):
                found = self.detect([item])
                self.assertEqual([entry["kind"] for entry in found], [kind])
                self.assertEqual(found[0]["suggested_action"], "upload")
                self.assertEqual(found[0]["platform"], "local")

    def test_many_images_are_one_collection_named_after_their_folder(self) -> None:
        found = self.detect([
            {"name": "1.jpg", "type": "image/jpeg", "size": 5, "path": "Chuyến đi/1.jpg"},
            {"name": "2.png", "type": "image/png", "size": 5, "path": "Chuyến đi/2.png"},
            {"name": "3.webp", "type": "image/webp", "size": 5, "path": "Chuyến đi/3.webp"},
        ])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "image_collection")
        self.assertEqual(found[0]["title"], "Chuyến đi")
        self.assertEqual(found[0]["metadata"]["file_count"], 3)

    def test_mixed_files_become_one_source_per_video_or_audio_and_one_for_the_pictures(self) -> None:
        found = self.detect([
            {"name": "a.jpg", "type": "image/jpeg", "size": 5},
            {"name": "clip.mp4", "type": "video/mp4", "size": 5},
            {"name": "b.jpg", "type": "image/jpeg", "size": 5},
            {"name": "voice.mp3", "type": "audio/mpeg", "size": 5},
            {"name": "note.pdf", "type": "application/pdf", "size": 5},
        ])
        self.assertEqual([item["kind"] for item in found], ["image_collection", "video", "audio", "unsupported"])
        self.assertEqual(found[0]["title"], "Bộ ảnh (2 ảnh)")
        self.assertEqual([entry["index"] for entry in found[0]["metadata"]["files"]], [0, 2])

    def test_files_the_importers_would_refuse_are_refused_here(self) -> None:
        found = self.detect([
            {"name": "x.heic", "type": "image/heic", "size": 5},
            {"name": "empty.mp4", "type": "video/mp4", "size": 0},
            {"name": "big.mp4", "type": "video/mp4", "size": 50},
        ], max_bytes=10)
        self.assertEqual([item["kind"] for item in found], ["unsupported"] * 3)
        self.assertEqual([item["suggested_action"] for item in found], ["none"] * 3)
        self.assertIn(".heic", found[0]["message"])


class _DbCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.database = Database(str(Path(self._tmp.name) / "t.db"))
        self.database.initialize()

    def tearDown(self) -> None:
        self._tmp.cleanup()


class _YouTube:
    api_key = "k"

    def __init__(self, videos=None, channel=None, error=None):
        self.videos, self.channel, self.error, self.calls = videos, channel, error, []

    def get_videos(self, ids):
        self.calls.append(("videos", ids))
        if self.error:
            raise self.error
        return self.videos

    def get_channel(self, reference):
        self.calls.append(("channel", reference))
        if self.error:
            raise self.error
        return self.channel


class YouTubeProbeTests(_DbCase):
    def test_a_stored_video_is_read_from_the_database(self) -> None:
        self.database.upsert_channel({"youtube_channel_id": "UC" + "a" * 22, "channel_url": "x", "title": "Kênh A"})
        self.database.upsert_video({"youtube_video_id": "dQw4w9WgXcQ", "youtube_channel_id": "UC" + "a" * 22,
                                    "video_url": "https://youtu.be/dQw4w9WgXcQ", "title": "Có sẵn", "duration_seconds": 62,
                                    "metadata_hash": "h"})
        youtube = _YouTube(error=AssertionError("API used"))
        found = detector.detect("https://youtu.be/dQw4w9WgXcQ", database=self.database, youtube=youtube)
        self.assertEqual(found["title"], "Có sẵn")
        self.assertEqual(found["metadata"]["channel_name"], "Kênh A")
        self.assertEqual(found["existing"], {"video_id": "dQw4w9WgXcQ", "is_source": False})
        self.assertEqual(youtube.calls, [])

    def test_a_new_video_costs_one_api_read(self) -> None:
        youtube = _YouTube(videos=[{
            "snippet": {"title": "Mới", "channelTitle": "Kênh B", "channelId": "UC" + "b" * 22,
                        "thumbnails": {"high": {"url": "https://i.ytimg.com/x.jpg"}}, "publishedAt": "2026-01-01T00:00:00Z"},
            "contentDetails": {"duration": "PT1M2S"}, "statistics": {"viewCount": "1200"},
        }])
        found = detector.detect("https://www.youtube.com/shorts/abcdefghijk", database=self.database, youtube=youtube)
        self.assertEqual(youtube.calls, [("videos", ["abcdefghijk"])])
        self.assertEqual((found["title"], found["metadata"]["duration_seconds"]), ("Mới", 62))
        self.assertEqual(found["metadata"]["channel_name"], "Kênh B")
        self.assertTrue(found["metadata"]["is_short"])

    def test_a_video_the_api_does_not_know_is_unreadable(self) -> None:
        found = detector.detect("https://youtu.be/abcdefghijk", database=self.database, youtube=_YouTube(videos=[]))
        self.assertEqual((found["status"], found["suggested_action"]), ("unreadable", "none"))

    def test_without_a_key_yt_dlp_reads_it(self) -> None:
        probe = mock.Mock(return_value={"title": "Qua yt-dlp", "channel_name": "Kênh C", "duration_seconds": 30,
                                        "thumbnail": "t", "video_id": "abcdefghijk", "webpage_url": "u"})
        found = detector.detect("https://youtu.be/abcdefghijk", database=self.database, youtube=None, probe_video=probe)
        probe.assert_called_once()
        self.assertEqual(found["title"], "Qua yt-dlp")

    def test_a_followed_channel_is_opened_not_added(self) -> None:
        self.database.upsert_channel({"youtube_channel_id": "UC" + "c" * 22, "handle": "@vuive", "channel_url": "x",
                                      "title": "Vui Vẻ", "subscriber_count": 1300000})
        youtube = _YouTube(error=AssertionError("API used"))
        for text in ("UC" + "c" * 22, "https://www.youtube.com/@VuiVe"):
            with self.subTest(text=text):
                found = detector.detect(text, database=self.database, youtube=youtube)
                self.assertEqual(found["suggested_action"], "open_channel")
                self.assertEqual(found["existing"], {"channel_id": "UC" + "c" * 22})
                self.assertEqual(found["title"], "Vui Vẻ")
        self.assertEqual(youtube.calls, [])

    def test_a_new_channel_is_looked_up_once(self) -> None:
        youtube = _YouTube(channel={"youtube_channel_id": "UC" + "d" * 22, "title": "Mới", "handle": "@moi",
                                    "thumbnail_url": "a.jpg", "subscriber_count": 10, "video_count": 3})
        found = detector.detect("@moi", database=self.database, youtube=youtube)
        self.assertEqual(found["suggested_action"], "add_channel")
        self.assertEqual(found["native_id"], "UC" + "d" * 22)
        self.assertEqual(len(youtube.calls), 1)

    def test_a_missing_channel_or_no_key(self) -> None:
        missing = detector.detect("@khongco", database=self.database,
                                  youtube=_YouTube(error=YouTubeApiError("x", status_code=404)))
        self.assertEqual(missing["status"], "unreadable")
        nokey = detector.detect("@moi", database=self.database, youtube=None)
        self.assertEqual(nokey["suggested_action"], "none")
        self.assertIn("khóa YouTube API", nokey["message"])


class OtherProbeTests(_DbCase):
    def test_a_tiktok_video_is_read_by_yt_dlp(self) -> None:
        probe = mock.Mock(return_value={"title": "Clip", "uploader": "@a", "duration_seconds": 15, "video_id": "web-1",
                                        "thumbnail": "t.jpg", "platform_slug": "tiktok", "webpage_url": "u"})
        found = detector.detect("https://www.tiktok.com/@a/video/7300000000000000000", database=self.database, probe_video=probe)
        self.assertEqual((found["title"], found["metadata"]["channel_name"]), ("Clip", "@a"))

    def test_a_video_that_cannot_be_read_is_not_offered(self) -> None:
        probe = mock.Mock(side_effect=SourceLinkError("ERROR: [TikTok] 7300: Unable to extract"))
        found = detector.detect("https://www.tiktok.com/@a/video/7300000000000000000", database=self.database, probe_video=probe)
        self.assertEqual((found["status"], found["suggested_action"]), ("unreadable", "none"))
        self.assertNotIn("ERROR", found["message"])

    def _product(self, read_status, **fields):
        return {"name": "Tai nghe S10", "read_status": read_status, "route": "session:profile:shopee",
                "session": "extension:coccoc", "attempts": ["profile:shopee: NEED_LOGIN - cookie"], **fields}

    def test_a_listing_read_by_the_product_reader(self) -> None:
        url = f"https://shopee.vn/Tai-Nghe-S10-i.1.{uuid.uuid4().int % 10**9}"
        reader = mock.Mock(return_value=self._product(
            "OK", price_text="₫9.999", seller="Shop A", images=["https://cf.shopee/x.jpg"],
            captured_at="2026-09-30T05:00:00+00:00"))
        found = detector.detect(url, database=self.database, read_product=reader)
        self.assertEqual((found["status"], found["title"]), ("detected", "Tai nghe S10"))
        self.assertEqual(found["metadata"]["price_text"], "₫9.999")
        self.assertEqual(found["metadata"]["captured_at"], "2026-09-30T05:00:00+00:00")
        self.assertEqual(found["thumbnail"], "https://cf.shopee/x.jpg")
        # The reader's routes and sessions stay on the server, for the import to reuse.
        text = json.dumps(found, ensure_ascii=False)
        for private in ("session", "attempts", "route", "cookie", "coccoc"):
            self.assertNotIn(private, text)
        self.assertEqual(detector.recent_product(url)["price_text"], "₫9.999")

    def test_a_page_that_does_not_name_the_listing_is_not_taken_for_it(self) -> None:
        # Measured 30/09 on TikTok Shop: served, but a price and seller of some other page.
        url = f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}"
        for name in ("", "Security Check"):
            with self.subTest(name=name):
                reader = mock.Mock(return_value={"name": name, "read_status": "OK", "price_text": "888.888₫",
                                                 "seller": "TikTok Shop Vietnam", "images": ["https://x/y.jpg"]})
                found = detector.detect(url, database=self.database, read_product=reader)
                self.assertEqual((found["status"], found["suggested_action"]), ("need_connection", "connect_platform"))
                self.assertEqual((found["metadata"]["price_text"], found["metadata"]["seller"], found["thumbnail"]), ("", "", ""))
                self.assertIn("không mở ra trang của sản phẩm này", found["message"])
                self.assertEqual(detector.recent_product(url), {})

    def test_a_structured_price_is_written_the_way_a_shop_writes_it(self) -> None:
        self.assertEqual(detector._price_label({"price": "119000.00", "currency": "VND"}), "119.000₫")
        self.assertEqual(detector._price_label({"price_text": "₫ 11.899", "price": "11899"}), "₫ 11.899")
        self.assertEqual(detector._price_label({"price": "12.5", "currency": "usd"}), "12.50 USD")
        self.assertEqual(detector._price_label({}), "")

    def test_a_listing_behind_a_sign_in_asks_for_a_connection_in_plain_words(self) -> None:
        url = f"https://shop.tiktok.com/vn/pdp/{uuid.uuid4().int % 10**18}"
        for status, expected in ((platform_connections.NEED_LOGIN, "need_connection"),
                                 (platform_connections.NEED_HUMAN_VERIFY, "need_connection"),
                                 (platform_connections.FAILED, "unreadable")):
            with self.subTest(status=status):
                reader = mock.Mock(return_value=self._product(status, name=""))
                found = detector.detect(url, database=self.database, read_product=reader)
                self.assertEqual(found["status"], expected)
                self.assertTrue(found["message"].startswith("Chưa đọc được thông tin sản phẩm"))
                for technical in ("NEED_", "extension", "profile", "session", "Cốc Cốc"):
                    self.assertNotIn(technical, found["message"])
                # Nothing to name it by: connecting comes first.
                self.assertEqual(found["suggested_action"], "connect_platform")
        self.assertEqual(detector.recent_product(url), {}, "a refused read is not reused")

    def test_an_article_from_its_own_tags(self) -> None:
        html = ('<html><head><meta property="og:title" content="Giá vàng hôm nay"><meta property="og:site_name" '
                'content="VnExpress"><meta property="og:image" content="https://i.vnecdn.net/a.jpg">'
                '<meta property="article:published_time" content="2026-09-30T08:00:00+07:00"></head></html>')
        found = detector.detect("https://vnexpress.net/gia-vang-hom-nay-4800000.html", database=self.database,
                                fetch_page=lambda url: html)
        self.assertEqual((found["kind"], found["title"]), ("article", "Giá vàng hôm nay"))
        self.assertEqual(found["metadata"]["site_name"], "VnExpress")
        self.assertEqual(found["thumbnail"], "https://i.vnecdn.net/a.jpg")

    def test_a_page_that_will_not_open_is_still_named(self) -> None:
        def blocked(url):
            raise page_source.PageSourceError("403")

        found = detector.detect("https://vnexpress.net/gia-vang-hom-nay-4800000.html", database=self.database,
                                fetch_page=blocked)
        self.assertEqual(found["kind"], "article")
        self.assertEqual(found["title"], "gia vang hom nay")
        self.assertNotIn("403", found["message"])
        walled = detector.detect("https://example.com/a", database=self.database,
                                 fetch_page=lambda url: "<title>Security Check</title>")
        self.assertNotEqual(walled["title"], "Security Check")

    def test_an_unknown_page_says_what_it_is(self) -> None:
        listing = '<script type="application/ld+json">{"@type":"Product","name":"Bình giữ nhiệt","offers":{"price":"199000","priceCurrency":"VND"}}</script>'
        article = '<meta property="og:type" content="article"><title>Một bài</title>'
        video = '<meta property="og:type" content="video.other"><title>Một clip</title>'
        probe = mock.Mock(return_value={"title": "Một clip", "duration_seconds": 40, "video_id": "web-2", "webpage_url": "u"})
        cases = ((listing, "product"), (article, "article"), (video, "video"))
        for html, kind in cases:
            with self.subTest(kind=kind):
                found = detector.detect("https://example.com/p/1", database=self.database, fetch_page=lambda url, h=html: h,
                                        probe_video=probe, extractor_of=lambda url: "")
                self.assertEqual(found["kind"], kind)
                self.assertEqual(found["detected_by"], "metadata_probe")

    def test_no_model_is_ever_asked(self) -> None:
        source = Path(detector.__file__).read_text(encoding="utf-8")
        for model in ("read_with_ai", "claude_code_bridge", "llm_client", "call_codex"):
            self.assertNotIn(model, source)
        with mock.patch.object(page_source, "read_with_ai", side_effect=AssertionError("AI used")):
            found = detector.detect("https://example.com/", database=self.database, fetch_page=lambda url: "",
                                    extractor_of=lambda url: "")
        self.assertEqual(found["kind"], "web")


if __name__ == "__main__":
    unittest.main()
