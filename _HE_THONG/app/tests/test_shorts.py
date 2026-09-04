"""A short is derived from the long video every workflow already produces."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import shorts
from youtube_monitor.database import Database
from youtube_monitor.shorts import (
    MAX_SHORT_SECONDS,
    ShortPlan,
    ShortsPlanError,
    build_plan,
    build_short_timeline,
    default_plan,
    fit_to_short,
    is_vertical,
    plan_duration_seconds,
    profile_size,
    set_plan_builder,
)


def _timeline(count: int = 4, seconds: float = 10.0) -> list[dict]:
    return [
        {
            "id": 100 + index,
            "segment_index": index,
            "duration_seconds": seconds,
            "voice_text": f"Loi thoai {index}",
            "subtitle_text": f"Phu de {index}",
            "visual_path": f"C:/x/hinh-{index}.png",
            "audio_path": f"C:/x/voice-{index}.wav",
        }
        for index in range(1, count + 1)
    ]


class ProfileTests(unittest.TestCase):
    def test_every_short_format_is_ten_eighty_by_nineteen_twenty(self) -> None:
        for profile in ("youtube_shorts", "instagram_reels", "tiktok", "facebook_reels"):
            self.assertEqual(profile_size(profile), (1080, 1920))
            self.assertTrue(is_vertical(profile))

    def test_facebook_feed_is_square(self) -> None:
        self.assertEqual(profile_size("facebook_feed"), (1080, 1080))
        self.assertFalse(is_vertical("facebook_feed"))

    def test_the_long_format_stays_landscape(self) -> None:
        self.assertEqual(profile_size("youtube_landscape"), (1920, 1080))
        self.assertFalse(is_vertical("youtube_landscape"))

    def test_an_unknown_profile_does_not_silently_go_vertical(self) -> None:
        self.assertEqual(profile_size("khong-biet"), (1920, 1080))
        self.assertFalse(is_vertical(""))


class SelectionTests(unittest.TestCase):
    def test_a_selection_is_capped_at_the_short_limit(self) -> None:
        timeline = _timeline(12, seconds=10)
        chosen = fit_to_short(timeline, [item["id"] for item in timeline])
        self.assertLessEqual(plan_duration_seconds(timeline, chosen), MAX_SHORT_SECONDS)
        self.assertEqual(len(chosen), 6)

    def test_scenes_keep_the_order_the_long_video_gave_them(self) -> None:
        """Out of order it reads as a different video, not a condensed one."""
        timeline = _timeline(4)
        chosen = fit_to_short(timeline, [103, 101, 104, 102])
        self.assertEqual(list(chosen), [101, 102, 103, 104])

    def test_ids_that_are_not_in_the_timeline_are_dropped(self) -> None:
        timeline = _timeline(3)
        self.assertEqual(list(fit_to_short(timeline, [101, 999])), [101])

    def test_a_repeated_id_is_only_used_once(self) -> None:
        timeline = _timeline(3)
        self.assertEqual(list(fit_to_short(timeline, [101, 101, 102])), [101, 102])

    def test_one_over_long_scene_is_still_kept_so_a_short_exists(self) -> None:
        timeline = _timeline(2, seconds=90)
        self.assertEqual(len(fit_to_short(timeline, [101, 102])), 1)


class DefaultPlanTests(unittest.TestCase):
    def test_a_plan_is_produced_without_any_model(self) -> None:
        plan = default_plan(_timeline(3), title="Tieu de")
        self.assertEqual(plan.title, "Tieu de")
        self.assertEqual(list(plan.segment_ids), [101, 102, 103])
        self.assertTrue(plan.hook)

    def test_a_scene_missing_its_voice_cannot_carry_a_short(self) -> None:
        timeline = _timeline(2)
        timeline[0]["audio_path"] = ""
        plan = default_plan(timeline)
        self.assertEqual(list(plan.segment_ids), [102])

    def test_a_timeline_with_nothing_finished_is_refused_clearly(self) -> None:
        timeline = _timeline(2)
        for item in timeline:
            item["visual_path"] = ""
        with self.assertRaises(ShortsPlanError) as ctx:
            default_plan(timeline)
        self.assertIn("hình", str(ctx.exception))


class ModelPlanTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_plan_builder(None)

    def test_the_model_choice_is_honoured_and_capped(self) -> None:
        timeline = _timeline(8, seconds=10)
        set_plan_builder(lambda request: {
            "title": "Ban ngan", "hook": "Moc cau", "reason": "vi sao",
            "segment_ids": [item["id"] for item in timeline],
            "captions": [{"segment_id": 102, "text": "Chu tren canh 2"}],
        })
        plan = build_plan(timeline, title="bo qua")
        self.assertEqual(plan.title, "Ban ngan")
        self.assertEqual(plan.hook, "Moc cau")
        self.assertEqual(plan.captions[102], "Chu tren canh 2")
        self.assertLessEqual(plan_duration_seconds(timeline, plan.segment_ids), MAX_SHORT_SECONDS)

    def test_a_model_that_picks_nothing_usable_does_not_lose_the_feature(self) -> None:
        timeline = _timeline(3)
        set_plan_builder(lambda request: {"segment_ids": [999], "title": "x", "hook": "y"})
        plan = build_plan(timeline)
        self.assertTrue(plan.segment_ids)

    def test_a_failing_model_is_reported_rather_than_swallowed(self) -> None:
        set_plan_builder(mock.Mock(side_effect=RuntimeError("het han muc")))
        with self.assertRaises(ShortsPlanError) as ctx:
            build_plan(_timeline(3))
        self.assertIn("het han muc", str(ctx.exception))

    def test_the_model_is_only_shown_scenes_that_are_finished(self) -> None:
        timeline = _timeline(3)
        timeline[1]["visual_path"] = ""
        seen: dict = {}
        set_plan_builder(lambda request: seen.update(request) or {"segment_ids": [101]})
        build_plan(timeline)
        self.assertEqual([item["segment_id"] for item in seen["segments"]], [101, 103])


class ShortTimelineTests(unittest.TestCase):
    def test_the_hook_lands_on_the_first_frames(self) -> None:
        timeline = _timeline(3)
        plan = ShortPlan(title="t", hook="Cau moc", segment_ids=(102, 103))
        built = build_short_timeline(timeline, plan)
        self.assertEqual(built[0]["subtitle_text"], "Cau moc")
        self.assertEqual(built[1]["subtitle_text"], "Phu de 3")

    def test_scenes_are_renumbered_for_the_new_edit(self) -> None:
        timeline = _timeline(4)
        plan = ShortPlan(title="t", hook="", segment_ids=(102, 104))
        built = build_short_timeline(timeline, plan)
        self.assertEqual([item["segment_index"] for item in built], [1, 2])

    def test_captions_replace_the_long_videos_subtitles(self) -> None:
        timeline = _timeline(3)
        plan = ShortPlan(title="t", hook="", segment_ids=(102,), captions={102: "Chu moi"})
        self.assertEqual(build_short_timeline(timeline, plan)[0]["subtitle_text"], "Chu moi")

    def test_the_source_timeline_is_not_mutated(self) -> None:
        timeline = _timeline(2)
        plan = ShortPlan(title="t", hook="Cau moc", segment_ids=(101,))
        build_short_timeline(timeline, plan)
        self.assertEqual(timeline[0]["subtitle_text"], "Phu de 1")

    def test_a_plan_pointing_at_deleted_scenes_is_refused(self) -> None:
        plan = ShortPlan(title="t", hook="", segment_ids=(999,))
        with self.assertRaises(ShortsPlanError):
            build_short_timeline(_timeline(2), plan)


class PlanStorageTests(unittest.TestCase):
    def _database(self, directory: str) -> tuple[Database, int]:
        database = Database(Path(directory) / "shorts.db")
        database.upsert_channel({
            "youtube_channel_id": "UC000000000000000000000B",
            "channel_url": "https://www.youtube.com/channel/UC000000000000000000000B",
            "title": "c", "uploads_playlist_id": "UU000000000000000000000B",
        })
        database.upsert_video({
            "youtube_video_id": "video-short-1",
            "youtube_channel_id": "UC000000000000000000000B",
            "video_url": "https://www.youtube.com/watch?v=video-short-1",
            "title": "t", "metadata_hash": "h", "raw_payload": {},
        })
        project = database.create_production_project("video-short-1")
        return database, int(project["id"])

    def test_a_plan_survives_a_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = self._database(directory)
            plan = ShortPlan(title="T", hook="H", segment_ids=(1, 2), captions={2: "c"})
            database.save_project_short(project_id, plan.as_dict(), duration_seconds=30)
            restored = ShortPlan.from_dict(database.get_project_short(project_id)["plan"])
            self.assertEqual(restored.segment_ids, (1, 2))
            self.assertEqual(restored.captions, {2: "c"})

    def test_replanning_drops_the_output_of_the_previous_plan(self) -> None:
        """A rendered file belongs to the plan that produced it."""
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = self._database(directory)
            database.save_project_short(project_id, {"title": "A", "segment_ids": [1]})
            database.save_project_short_output(project_id, "C:/x/final_short.mp4")
            database.save_project_short(project_id, {"title": "B", "segment_ids": [2]})
            self.assertEqual(database.get_project_short(project_id)["output_path"], "")

    def test_a_short_for_a_missing_project_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, _ = self._database(directory)
            with self.assertRaises(ValueError):
                database.save_project_short(9999, {"title": "x"})


class RendererFitTests(unittest.TestCase):
    def test_the_renderer_can_fill_a_frame_as_well_as_pad_it(self) -> None:
        import inspect

        from youtube_monitor.ffmpeg_renderer import _segment_arguments, render_timeline_with_ffmpeg

        self.assertIn("fit", inspect.signature(render_timeline_with_ffmpeg).parameters)
        # fit must stay last: the caller passes everything before it positionally.
        self.assertEqual(list(inspect.signature(_segment_arguments).parameters)[-1], "fit")

    def test_padding_stays_the_default_so_the_long_edit_is_unchanged(self) -> None:
        import inspect

        from youtube_monitor.ffmpeg_renderer import render_timeline_with_ffmpeg

        self.assertEqual(
            inspect.signature(render_timeline_with_ffmpeg).parameters["fit"].default, "pad"
        )

    def test_the_short_job_is_a_job_type_the_worker_accepts(self) -> None:
        from youtube_monitor.production_worker import JOB_TYPES

        self.assertIn("render_short", JOB_TYPES)


class ShortIsReachableFromThePageTests(unittest.TestCase):
    """A feature with no control is the defect this project keeps finding."""

    def setUp(self) -> None:
        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

    def test_short_controls_live_in_the_main_wizard_lane(self) -> None:
        self.assertNotIn('id="studioPlanShortButton"', self.page)
        self.assertNotIn('id="studioRenderShortButton"', self.page)
        self.assertIn("queueShortVariantJob('voiceover')", self.page)
        self.assertIn("queueShortVariantJob('render_short')", self.page)

    def test_the_wizard_uses_the_standalone_short_lane(self) -> None:
        self.assertIn("/short-lane", self.page)
        self.assertIn("variant: 'short'", self.page)
        self.assertIn("'render_short'", self.page)

    def test_the_short_visual_lane_is_vertical(self) -> None:
        self.assertIn("variant === 'short' ? '720:1280'", self.page)

    def test_the_short_endpoints_are_registered(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/projects/{project_id}/short/plan", paths)
        self.assertIn("/api/projects/{project_id}/short", paths)


if __name__ == "__main__":
    unittest.main()


class ShortRenderIsQueuedCorrectlyTests(unittest.TestCase):
    """The lane sends the Short variant and confirmation in the request body."""

    def setUp(self) -> None:
        self.page = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "templates" / "index.html"
        ).read_text(encoding="utf-8")

    def test_confirmation_travels_in_the_body_where_the_model_reads_it(self) -> None:
        start = self.page.index("async function queueShortVariantJob")
        body = self.page[start:start + 1800]
        self.assertIn("job_type: jobType, provider, confirmed: true, variant: 'short'", body)
        self.assertNotIn("/jobs?confirmed=true", self.page)

    def test_the_request_carries_only_fields_the_model_declares(self) -> None:
        from youtube_monitor.main import CreateProductionJobRequest

        allowed = set(CreateProductionJobRequest.model_fields)
        self.assertIn("confirmed", allowed)
        self.assertNotIn("script_id", allowed)
        start = self.page.index("async function queueShortVariantJob")
        body = self.page[start:start + 1800]
        self.assertNotIn("script_id", body)

    def test_it_targets_the_short_script_explicitly(self) -> None:
        start = self.page.index("async function queueShortVariantJob")
        body = self.page[start:start + 1800]
        self.assertIn("variant: 'short'", body)
