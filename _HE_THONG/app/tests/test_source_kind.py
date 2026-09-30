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
    ]

    def test_each_older_shape(self) -> None:
        for row, payload, kind in self.CASES:
            with self.subTest(row=row["youtube_video_id"]):
                self.assertEqual(source_kinds.for_row(row, payload), kind)

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
        self.sql("UPDATE videos SET source_kind = ''")  # as a database from before the column
        Database(self.path).initialize()
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


if __name__ == "__main__":
    unittest.main()
