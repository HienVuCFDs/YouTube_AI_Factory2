"""One brief, whatever the source was.

The analysis step assumed a video, and asked a model for SEO notes from the
title while the app held a transcript it had just paid Whisper to make and no
frames at all. These tests cover the shape that replaced it: extraction knows
what kind of source this is and understands nothing, analysis is one call, and
what the source could *not* supply is stated by the side that did the handing
over rather than asked of the model.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from youtube_monitor import source_brief


def _sheet(root: Path) -> Path:
    path = root / "sheet.jpg"
    path.write_bytes(b"jpeg")
    return path


class WhatKindOfSourceThisIsTests(unittest.TestCase):
    def test_a_real_video_row_is_a_video(self) -> None:
        video = {"youtube_video_id": "abc123", "duration_seconds": 62}

        self.assertEqual(source_brief.detect_kind({}, video, []), "video")

    def test_an_idea_project_is_not_a_source(self) -> None:
        """Idea projects are stored against a placeholder row, so the presence
        of a row is not by itself something to analyse."""
        placeholder = {"youtube_video_id": "idea-9f2c", "duration_seconds": 0}

        self.assertEqual(source_brief.detect_kind({}, placeholder, []), "idea")

    def test_a_row_with_text_and_no_running_time_is_an_article(self) -> None:
        article = {"youtube_video_id": "web-1", "duration_seconds": 0, "description": "Bài viết dài"}

        self.assertEqual(source_brief.detect_kind({}, article, []), "article")

    def test_uploaded_pictures_and_nothing_else_are_the_source(self) -> None:
        assets = [{"asset_type": "image", "file_path": "a.png"}]

        self.assertEqual(source_brief.detect_kind({}, None, assets), "images")

    def test_nothing_at_all_is_an_idea(self) -> None:
        self.assertEqual(source_brief.detect_kind({}, None, []), "idea")


class WhatTheSourceCouldNotSupplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_pictures_carry_a_look_and_no_story(self) -> None:
        extraction = source_brief.Extraction(kind="images", image_sheet=_sheet(self.root), image_count=4)

        self.assertTrue(extraction.has_visual_style)
        self.assertFalse(extraction.has_story)
        self.assertFalse(extraction.has_dialogue)

    def test_an_article_carries_a_story_and_no_look(self) -> None:
        extraction = source_brief.Extraction(kind="article", text="Nội dung bài")

        self.assertTrue(extraction.has_story)
        self.assertFalse(extraction.has_visual_style)
        # Prose is not dialogue: nobody in an article says anything aloud.
        self.assertFalse(extraction.has_dialogue)

    def test_a_video_with_a_transcript_carries_both(self) -> None:
        extraction = source_brief.Extraction(
            kind="video", text="Lời thoại", image_sheet=_sheet(self.root),
        )

        self.assertTrue(extraction.has_story)
        self.assertTrue(extraction.has_dialogue)
        self.assertTrue(extraction.has_visual_style)


class WhatTheAppSettlesRatherThanAsksTests(unittest.TestCase):
    """A model told to look at pictures it never received will describe them."""

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_a_style_described_without_pictures_is_discarded(self) -> None:
        extraction = source_brief.Extraction(kind="article", text="Bài viết")
        parsed = {"visual_style": "Tông xanh, ánh sáng dịu", "limitations": []}

        brief = source_brief.finalise(parsed, extraction, "codex_cli")

        self.assertEqual(brief["visual_style"], "")
        self.assertFalse(brief["has_visual_style"])

    def test_a_style_described_with_pictures_is_kept(self) -> None:
        extraction = source_brief.Extraction(
            kind="images", image_sheet=_sheet(self.root), image_count=3,
        )
        brief = source_brief.finalise({"visual_style": "Tông xanh"}, extraction, "codex_cli")

        self.assertEqual(brief["visual_style"], "Tông xanh")

    def test_dialogue_invented_for_a_silent_source_is_dropped(self) -> None:
        extraction = source_brief.Extraction(kind="images", image_sheet=_sheet(self.root))
        parsed = {"dialogue": [{"order": 1, "speaker": "Nam", "line": "Xin chào"}]}

        self.assertEqual(source_brief.finalise(parsed, extraction, "x")["dialogue"], [])

    def test_the_gaps_are_named_before_the_model_speaks(self) -> None:
        """What is missing is a fact about the handover, so the side that did
        the handing over states it."""
        extraction = source_brief.Extraction(kind="images", image_sheet=_sheet(self.root))

        limitations = source_brief.finalise({"limitations": ["Ảnh hơi mờ"]}, extraction, "x")["limitations"]

        self.assertIn("do AI sáng tác", " ".join(limitations))
        self.assertEqual(limitations[-1], "Ảnh hơi mờ")

    def test_a_source_that_supplied_everything_adds_no_warnings(self) -> None:
        extraction = source_brief.Extraction(
            kind="video", text="Lời thoại", image_sheet=_sheet(self.root),
        )

        self.assertEqual(source_brief.finalise({"limitations": []}, extraction, "x")["limitations"], [])


class WhatTheModelIsToldTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_a_source_with_no_pictures_says_so_in_the_prompt(self) -> None:
        """Stated as a fact, because a model honours "there is none" and
        ignores "do not invent" when nothing says the thing is absent."""
        prompt = source_brief.build_prompt(source_brief.Extraction(kind="article", text="Bài"))

        self.assertIn("KHONG duoc dua bat ky hinh anh nao", prompt)

    def test_a_picture_only_source_is_told_the_story_will_be_invented(self) -> None:
        extraction = source_brief.Extraction(kind="images", image_sheet=_sheet(self.root), image_count=5)

        self.assertIn("khong co cot chuyen", source_brief.build_prompt(extraction))

    def test_the_transcript_is_actually_in_the_prompt(self) -> None:
        """The old analyser was handed the title and the description only,
        while the app held a transcript it had paid for."""
        extraction = source_brief.Extraction(
            kind="video", text="Trái Đất hình thành từ tinh vân", text_label="Loi thoai",
            metadata={"title": "Trái Đất"},
        )

        self.assertIn("Trái Đất hình thành từ tinh vân", source_brief.build_prompt(extraction))


class TheOlderShapeIsDerivedNotAskedAgainTests(unittest.TestCase):
    def test_the_metadata_row_comes_from_the_one_brief(self) -> None:
        brief = {"topic": "Trái Đất", "language": "vi", "content_type": "explainer",
                 "keywords": ["vũ trụ", "hành tinh"], "provider": "codex_cli"}

        row = source_brief.metadata_row(brief, "Trái Đất được tạo ra thế nào")

        self.assertEqual(row["topic"], "Trái Đất")
        self.assertEqual([item["keyword"] for item in row["keywords"]], ["vũ trụ", "hành tinh"])
        self.assertEqual(row["source_type"], "metadata")


class ReadingAnArticleTests(unittest.TestCase):
    def test_markup_is_not_part_of_the_text(self) -> None:
        body = source_brief.article_text(
            "<html><script>var a=1;</script><p>Trái Đất 4,5 tỉ năm.</p></html>"
        )

        self.assertEqual(body, "Trái Đất 4,5 tỉ năm.")

    def test_plain_text_passes_through_unharmed(self) -> None:
        self.assertEqual(source_brief.article_text("  Một   câu  "), "Một câu")


if __name__ == "__main__":
    unittest.main()


class ASilentVideoIsStillASourceTests(unittest.TestCase):
    """A music video, a timelapse, gameplay or plain b-roll has pictures and
    no words - the same situation as a folder of images, not a failure. The
    step used to refuse outright and stop the whole run."""

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_frames_alone_still_carry_a_look(self) -> None:
        extraction = source_brief.Extraction(
            kind="video", text="", image_sheet=_sheet(self.root), image_count=12,
        )

        self.assertFalse(extraction.has_dialogue)
        self.assertFalse(extraction.has_story)
        self.assertTrue(extraction.has_visual_style)

    def test_the_model_is_not_told_a_transcript_is_attached(self) -> None:
        """Saying the transcript is there when it is not is how a model ends
        up quoting lines nobody said."""
        extraction = source_brief.Extraction(
            kind="video", text="", image_sheet=_sheet(self.root), image_count=12,
        )

        prompt = source_brief.build_prompt(extraction)

        self.assertIn("KHONG CO LOI NOI", prompt)
        self.assertNotIn("Ban nhan loi thoai da phien am va", prompt)

    def test_a_video_with_speech_is_told_the_usual_thing(self) -> None:
        extraction = source_brief.Extraction(
            kind="video", text="Xin chào", image_sheet=_sheet(self.root), image_count=12,
        )

        self.assertIn("Ban nhan loi thoai da phien am", source_brief.build_prompt(extraction))

    def test_invented_dialogue_is_dropped_for_a_silent_video(self) -> None:
        extraction = source_brief.Extraction(kind="video", text="", image_sheet=_sheet(self.root))
        parsed = {"dialogue": [{"order": 1, "speaker": "Nam", "line": "Chưa từng nói"}]}

        brief = source_brief.finalise(parsed, extraction, "codex_cli")

        self.assertEqual(brief["dialogue"], [])
        self.assertIn("do AI sáng tác", " ".join(brief["limitations"]))


class HowMuchPictureIsWorthFetchingTests(unittest.TestCase):
    """The sheet scales every tile to 320px wide whatever it was given, but
    the download grows with the length of the source while the sheet does not.
    A minute costs about 4 MB at 480p; two hours would cost 450 MB to produce
    exactly the same twelve tiles."""

    def test_a_short_clip_keeps_the_sharper_copy(self) -> None:
        """Sharpness survives the downscale and is what lets a model read
        burned-in text - which has already caught one mis-transcription."""
        self.assertEqual(source_brief.preview_height(62), 480)
        self.assertEqual(source_brief.preview_height(9 * 60), 480)

    def test_a_long_video_is_not_fetched_at_full_size_for_twelve_frames(self) -> None:
        self.assertEqual(source_brief.preview_height(30 * 60), 360)
        self.assertEqual(source_brief.preview_height(3 * 60 * 60), 240)

    def test_an_unknown_length_is_treated_as_short(self) -> None:
        """Guessing low would cost a short video its readable text for nothing."""
        self.assertEqual(source_brief.preview_height(0), 480)
        self.assertEqual(source_brief.preview_height(None), 480)
