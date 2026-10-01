"""One field says what a source is: videos.source_kind.

Stated by the importer when the row is written, filled in once for rows from
before, and read - not worked out again - by everything after.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from youtube_monitor import source_kinds
from youtube_monitor.database import Database


class TheRuleForRowsThatDoNotSayTests(unittest.TestCase):
    CASES = [
        # row, payload, kind
        ({"youtube_video_id": "abcdefghijk", "duration_seconds": 62}, {"kind": "youtube#video"}, "video"),
        ({"youtube_video_id": "web-1", "duration_seconds": 0, "description": "Bài dài", "video_url": "https://bao.test/a"},
         {"source": "link_import", "platform": "web"}, "article"),
        ({"youtube_video_id": "web-2", "duration_seconds": 0, "description": "", "video_url": "https://bao.test/b"},
         {"source": "link_import", "platform": "web"}, "web"),
        ({"youtube_video_id": "web-3", "duration_seconds": 0, "video_url": "https://shopee.vn/x-i.1.2"},
         {"source": "link_import", "platform": "shop"}, "product"),
        ({"youtube_video_id": "web-4", "duration_seconds": 30, "video_url": "https://www.tiktok.com/@a/video/1"},
         {"source": "link_import", "platform": "TikTok"}, "video"),
        ({"youtube_video_id": "web-5", "duration_seconds": 0, "video_url": "https://x.test/y"},
         {"source": "article_import"}, "article"),
        ({"youtube_video_id": "local-1", "duration_seconds": 10}, {"media_kind": "audio"}, "audio"),
        ({"youtube_video_id": "local-2", "duration_seconds": 10}, {"media_kind": "video"}, "video"),
        ({"youtube_video_id": "idea-1"}, {"source": "high_level_request"}, ""),
        ({"youtube_video_id": "idea-2"}, {"source": "image_collection"}, "image_collection"),
        # A YouTube row pushed by WebSub carries no API payload and no running time.
        ({"youtube_video_id": "dQw4w9WgXcQ", "youtube_channel_id": "UC" + "a" * 22}, {"video_id": "dQw4w9WgXcQ"}, "video"),
        # yt-dlp read it as a film (a TikTok photo post has no running time).
        ({"youtube_video_id": "web-6", "duration_seconds": 0}, {"source": "link_import", "platform": "TikTok"}, "video"),
        # An upload: the probe of the bytes, or only the file's name, says audio.
        ({"youtube_video_id": "local-3", "duration_seconds": 10, "media_kind": "audio"}, {}, "audio"),
        ({"youtube_video_id": "local-4", "duration_seconds": 10, "local_media_path": r"F:\x\giong.MP3"}, {}, "audio"),
        # Nothing to go on: a web page, the kind that claims nothing.
        ({"youtube_video_id": "web-7", "duration_seconds": 0, "video_url": "https://x.test/y"}, {}, "web"),
        ({"youtube_video_id": "web-8", "duration_seconds": None, "video_url": "https://x.test/z"}, {}, "web"),
    ]

    def test_each_older_shape(self) -> None:
        for row, payload, kind in self.CASES:
            with self.subTest(row=row["youtube_video_id"]):
                self.assertEqual(source_kinds.for_row(row, payload), kind)

    def test_it_never_reaches_for_the_network(self) -> None:
        from unittest import mock

        with mock.patch("httpx.get", side_effect=AssertionError("network")), \
                mock.patch("httpx.Client.send", side_effect=AssertionError("network")):
            for row, payload, _ in self.CASES:
                source_kinds.for_row(row, payload)

    def test_only_the_six_kinds_are_accepted(self) -> None:
        self.assertEqual(source_kinds.SOURCE_KINDS, ("video", "article", "product", "image_collection", "audio", "web"))
        self.assertEqual(source_kinds.valid("Article"), "article")
        self.assertEqual(source_kinds.valid("images"), "")


class _DbCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "t.db")
        self.database = Database(self.path)
        self.database.initialize()
        self.database.upsert_channel({"youtube_channel_id": "site-x", "channel_url": "x"})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sql(self, statement: str, *args) -> list[tuple]:
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            with connection:
                return connection.execute(statement, args).fetchall()

    def kind(self, video_id: str) -> str:
        return self.database.get_video(video_id)["source_kind"]

    def add(self, video_id: str, **fields) -> None:
        self.database.upsert_video({"youtube_video_id": video_id, "youtube_channel_id": "site-x",
                                    "video_url": fields.pop("video_url", f"https://x.test/{video_id}"),
                                    "metadata_hash": "h", **fields})


class WritingTheKindTests(_DbCase):
    def test_a_stated_kind_is_stored_and_stays(self) -> None:
        self.add("web-a", duration_seconds=0, description="Có mô tả", source_kind="web")
        self.assertEqual(self.kind("web-a"), "web", "the importer's word, not the rule's")
        self.add("web-a", duration_seconds=0, description="Có mô tả")
        self.assertEqual(self.kind("web-a"), "web", "a later write that says nothing changes nothing")
        self.add("web-a", duration_seconds=0, source_kind="article")
        self.assertEqual(self.kind("web-a"), "article", "a later write that says so does")

    def test_a_writer_that_says_nothing_gets_the_rule_once(self) -> None:
        self.add("abcdefghijk", duration_seconds=62, raw_payload={"kind": "youtube#video"})
        self.assertEqual(self.kind("abcdefghijk"), "video")

    def test_an_idea_is_not_a_source_and_pictures_are(self) -> None:
        idea = self.database.create_idea_project("Một ý tưởng")
        pictures = self.database.create_idea_project("Bộ ảnh", source="image_collection")
        self.assertEqual(self.kind(idea["youtube_video_id"]), "")
        self.assertEqual(self.kind(pictures["youtube_video_id"]), "image_collection")

    def test_marking_a_source_writes_its_kind_on_the_row(self) -> None:
        self.add("web-b", duration_seconds=0, description="x")
        item = self.database.record_source_item("web-b", kind="product", platform="shopee")
        self.assertEqual((item["source_kind"], self.kind("web-b")), ("product", "product"))
        columns = {row[1] for row in self.sql("PRAGMA table_info(source_items)")}
        self.assertNotIn("kind", columns, "the kind lives on the row only")


class RowsFromBeforeTests(_DbCase):
    def test_every_older_row_is_given_its_kind_at_start(self) -> None:
        self.add("abcdefghijk", duration_seconds=62, raw_payload={"kind": "youtube#video"})
        self.add("web-art", duration_seconds=0, description="Bài", raw_payload={"source": "link_import", "platform": "web"})
        self.add("web-page", duration_seconds=0, raw_payload={"source": "link_import", "platform": "web"})
        self.add("web-shop", duration_seconds=0, video_url="https://shopee.vn/x-i.1.2",
                 raw_payload={"source": "link_import", "platform": "shop"})
        self.add("local-a", duration_seconds=5, raw_payload={"media_kind": "audio"})
        idea = self.database.create_idea_project("Ý tưởng")["youtube_video_id"]
        project = self.database.create_production_project("web-art", title="Dự án cũ")
        before = self.sql("SELECT youtube_video_id, youtube_channel_id, title, metadata_hash FROM videos ORDER BY id")
        self.sql("UPDATE videos SET source_kind = ''")  # as a database from before the column
        Database(self.path).initialize()
        # Only the kind is written: no key, channel, title or project moves.
        self.assertEqual(self.sql("SELECT youtube_video_id, youtube_channel_id, title, metadata_hash FROM videos ORDER BY id"), before)
        self.assertEqual(self.database.get_production_project(int(project["id"]))["youtube_video_id"], "web-art")
        self.assertEqual(
            {key: self.kind(key) for key in ("abcdefghijk", "web-art", "web-page", "web-shop", "local-a", idea)},
            {"abcdefghijk": "video", "web-art": "article", "web-page": "web", "web-shop": "product",
             "local-a": "audio", idea: ""},
        )

    def test_the_first_cut_of_the_source_list_moves_its_kind_onto_the_row(self) -> None:
        self.add("web-old", duration_seconds=0, description="x")
        self.sql("DROP TABLE source_items")
        self.sql("""CREATE TABLE source_items (youtube_video_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '', detected_by TEXT NOT NULL DEFAULT '',
                    snapshot_json TEXT NOT NULL DEFAULT '{}', added_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.sql("INSERT INTO source_items VALUES ('web-old', 'product', 'shopee', 'product_reader', "
                 "'{\"price_text\": \"9.999₫\"}', '2026-09-30T00:00:00', '2026-09-30T00:00:00')")
        Database(self.path).initialize()
        self.assertEqual(self.kind("web-old"), "product")
        rows = self.sql("SELECT youtube_video_id, platform, snapshot_json, added_at FROM source_items")
        self.assertEqual(rows, [("web-old", "shopee", '{"price_text": "9.999₫"}', "2026-09-30T00:00:00")])
        self.assertNotIn("kind", {row[1] for row in self.sql("PRAGMA table_info(source_items)")})


class ThePlanReadsTheSameKindTests(unittest.TestCase):
    def test_the_analysis_first_then_the_row_and_the_platform_only_for_old_rows(self) -> None:
        from youtube_monitor.project_planner import source_kind

        cases = [
            ({"source_type": "product"}, {"platform": "web"}, "web", "product"),  # what was analysed
            ({"source_type": "idea"}, {}, "product", "idea"),  # the page could not be read: analysed as an idea
            ({}, {"platform": "upload"}, "audio", "video"),  # spoken audio researched like a video's content
            ({"source_type": "web"}, {}, "web", "article"),  # a page researched like an article
            ({}, {}, "image_collection", "images"),
            ({}, {"platform": "shop"}, "", "product"),  # a row from before source_kind
        ]
        for result, identity, stored, expected in cases:
            with self.subTest(stored=stored, result=result):
                self.assertEqual(source_kind(result, identity, stored), expected)


class ThePayloadBugTests(_DbCase):
    """The marker saying "article" or "product" was written into raw_payload_json,
    and the consumers looked for it in raw_payload - which get_video leaves out.
    Now the kind is on the row, and nothing reads the payload for it."""

    def test_a_marker_only_in_the_payload_reaches_every_consumer_through_the_column(self) -> None:
        from youtube_monitor import source_brief
        from youtube_monitor.project_context import build_source_package

        self.add("web-art", duration_seconds=0, raw_payload={"source": "article_import", "platform": "web"})
        self.add("web-shop", duration_seconds=0, raw_payload={"source": "product_import", "platform": "web"})
        self.sql("UPDATE videos SET source_kind = ''")  # a database from before the column
        Database(self.path).initialize()
        for key, kind, read_as in (("web-art", "article", "article"), ("web-shop", "product", "product")):
            with self.subTest(key=key):
                row = self.database.get_video(key)
                self.assertNotIn("raw_payload", row)
                self.assertNotIn("raw_payload_json", row)
                self.assertEqual(row["source_kind"], kind)
                self.assertEqual(source_brief.detect_kind({}, row, []), read_as)
                project = self.database.create_production_project(key, title=key)
                self.assertEqual(build_source_package(self.database, int(project["id"]))["source"]["source_kind"], kind)

    def test_no_consumer_reads_the_payload_for_the_kind(self) -> None:
        import inspect

        from tests.ui_source import studio_ui
        from youtube_monitor import main, project_context, source_brief

        for name, code in (
            ("source_brief", inspect.getsource(source_brief)),
            ("extract_source", inspect.getsource(main.extract_source)),
            ("_step_analyze", inspect.getsource(main._step_analyze)),
            ("_source_view", inspect.getsource(main._source_view)),
            ("build_source_package", inspect.getsource(project_context.build_source_package)),
            ("_source_origin", inspect.getsource(project_context._source_origin)),
        ):
            with self.subTest(name=name):
                self.assertNotIn("raw_payload", code)
        ui = studio_ui()
        kind = ui[ui.index("function studioSourceKind("):ui.index("\n  }\n", ui.index("function studioSourceKind("))]
        audio = ui[ui.index("function studioSourceIsAudio("):ui.index("\n  }\n", ui.index("function studioSourceIsAudio("))]
        for guess in ("raw_payload", "duration_seconds", "startsWith('web-')", "extension", "title"):
            self.assertNotIn(guess, kind + audio, guess)


if __name__ == "__main__":
    unittest.main()
