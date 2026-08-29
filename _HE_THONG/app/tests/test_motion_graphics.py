from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from youtube_monitor import motion_graphics
from youtube_monitor.motion_graphics import (
    DEFAULT_THEME,
    MOTION_CUT_TYPES,
    MotionGraphicsError,
    _target_size,
    build_cut_spec,
    build_props,
    composer_ready,
    generate_motion_graphics_scene,
    set_spec_builder,
)
from youtube_monitor.providers import SCENE_VIDEO
from youtube_monitor.scene_generator import build_scene_provider_gateway


def _job(**overrides: object) -> dict[str, object]:
    job = {
        "id": 11,
        "project_id": 3,
        "timeline_segment_id": 9,
        "prompt": "Một biểu đồ cột về chi phí từng provider",
        "duration_seconds": 5,
        "ratio": "1280:720",
    }
    job.update(overrides)
    return job


class CutSpecTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_spec_builder(None)

    def test_a_caller_supplied_json_spec_is_used_as_is(self) -> None:
        spec = {"type": "bar_chart", "chartData": [{"label": "A", "value": 1}]}
        built = build_cut_spec(_job(prompt=json.dumps(spec)))
        self.assertEqual(built["type"], "bar_chart")
        self.assertEqual(built["chartData"], spec["chartData"])

    def test_prose_falls_back_to_a_typographic_card_rather_than_failing(self) -> None:
        """A missing model should degrade the scene, not lose the job."""
        built = build_cut_spec(_job())
        self.assertEqual(built["type"], "text_card")
        self.assertIn("biểu đồ cột", built["text"])

    def test_the_app_can_convert_prose_into_a_spec(self) -> None:
        set_spec_builder(lambda job: {"type": "stat_card", "stat": "564"})
        built = build_cut_spec(_job())
        self.assertEqual(built, {"type": "stat_card", "stat": "564"})

    def test_a_spec_naming_an_unknown_type_is_refused(self) -> None:
        set_spec_builder(lambda job: {"type": "hologram", "text": "x"})
        self.assertEqual(build_cut_spec(_job())["type"], "text_card")

    def test_broken_json_falls_back_instead_of_raising(self) -> None:
        built = build_cut_spec(_job(prompt='{"type": "bar_chart", oops'))
        self.assertEqual(built["type"], "text_card")

    def test_a_failing_spec_builder_is_reported_clearly(self) -> None:
        set_spec_builder(mock.Mock(side_effect=RuntimeError("model het han muc")))
        with self.assertRaises(MotionGraphicsError) as ctx:
            build_cut_spec(_job())
        self.assertIn("model het han muc", str(ctx.exception))

    def test_an_empty_prompt_is_refused(self) -> None:
        with self.assertRaises(MotionGraphicsError):
            build_cut_spec(_job(prompt="   "))

    def test_every_documented_cut_type_is_accepted(self) -> None:
        for cut_type in MOTION_CUT_TYPES:
            built = build_cut_spec(_job(prompt=json.dumps({"type": cut_type})))
            self.assertEqual(built["type"], cut_type)


class PropsTests(unittest.TestCase):
    def test_the_cut_is_given_the_scene_length_the_job_asked_for(self) -> None:
        props = build_props(_job(duration_seconds=8), {"type": "text_card", "text": "x"})
        cut = props["cuts"][0]
        self.assertEqual(cut["in_seconds"], 0)
        self.assertEqual(cut["out_seconds"], 8)

    def test_a_theme_is_always_set_so_text_cannot_render_invisible(self) -> None:
        """Without a theme the composition draws dark text on a dark ground."""
        props = build_props(_job(), {"type": "text_card", "text": "x"})
        self.assertEqual(props["theme"], DEFAULT_THEME)

    def test_an_unknown_theme_falls_back_rather_than_reaching_the_renderer(self) -> None:
        props = build_props(_job(), {"type": "text_card", "text": "x", "theme": "neon-vaporwave"})
        self.assertEqual(props["theme"], DEFAULT_THEME)

    def test_a_known_theme_is_honoured(self) -> None:
        props = build_props(_job(), {"type": "text_card", "text": "x", "theme": "clean-professional"})
        self.assertEqual(props["theme"], "clean-professional")

    def test_the_theme_is_not_left_inside_the_cut(self) -> None:
        props = build_props(_job(), {"type": "text_card", "text": "x", "theme": "clean-professional"})
        self.assertNotIn("theme", props["cuts"][0])

    def test_component_fields_survive_into_the_cut(self) -> None:
        spec = {"type": "bar_chart", "title": "Chi phí", "chartData": [{"label": "A", "value": 2}]}
        cut = build_props(_job(), spec)["cuts"][0]
        self.assertEqual(cut["title"], "Chi phí")
        self.assertEqual(cut["chartData"], spec["chartData"])

    def test_the_composition_gets_the_empty_tracks_it_expects(self) -> None:
        props = build_props(_job(), {"type": "text_card", "text": "x"})
        self.assertEqual(props["overlays"], [])
        self.assertEqual(props["captions"], [])
        self.assertEqual(props["audio"], {})


class TargetSizeTests(unittest.TestCase):
    def test_reads_the_project_ratio(self) -> None:
        self.assertEqual(_target_size("720:1280"), (720, 1280))

    def test_falls_back_when_unusable(self) -> None:
        for value in ("", "abc", "0:0"):
            self.assertEqual(_target_size(value), (1280, 720))


class ComposerReadinessTests(unittest.TestCase):
    def test_the_copied_composer_is_present_and_installed(self) -> None:
        ready, detail = composer_ready()
        self.assertTrue(ready, detail)

    def test_a_missing_composer_is_reported_not_hidden(self) -> None:
        with mock.patch.object(motion_graphics, "COMPOSER_ROOT", Path("khong-ton-tai")):
            ready, detail = composer_ready()
        self.assertFalse(ready)
        self.assertIn("Khong tim thay", detail)


class GenerateSceneTests(unittest.TestCase):
    def test_a_finished_scene_returns_its_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def fake_render(props, destination):
                destination.write_bytes(b"raw")

            def fake_normalise(source_path, output_path, **_):
                output_path.write_bytes(b"mp4")

            with mock.patch.object(motion_graphics, "_render_composition", side_effect=fake_render):
                with mock.patch.object(motion_graphics, "_normalise_clip", side_effect=fake_normalise):
                    output = generate_motion_graphics_scene(None, _job(), Path(directory))
            path = Path(output)
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "motion-segment-9-job-11.mp4")

    def test_the_untrimmed_render_is_not_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def fake_render(props, destination):
                destination.write_bytes(b"raw")

            def fake_normalise(source_path, output_path, **_):
                output_path.write_bytes(b"mp4")

            with mock.patch.object(motion_graphics, "_render_composition", side_effect=fake_render):
                with mock.patch.object(motion_graphics, "_normalise_clip", side_effect=fake_normalise):
                    output = generate_motion_graphics_scene(None, _job(), Path(directory))
            self.assertEqual(list(Path(output).parent.glob("*.raw.mp4")), [])

    def test_a_failed_render_still_clears_its_scratch_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def fake_render(props, destination):
                destination.write_bytes(b"raw")
                raise MotionGraphicsError("Remotion render that bai")

            with mock.patch.object(motion_graphics, "_render_composition", side_effect=fake_render):
                with self.assertRaises(MotionGraphicsError):
                    generate_motion_graphics_scene(None, _job(), Path(directory))
            leftovers = list(Path(directory).rglob("*.raw.mp4"))
            self.assertEqual(leftovers, [])


class MotionProviderRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.descriptor = build_scene_provider_gateway().require("motion_graphics").descriptor

    def test_registered_as_a_free_local_video_source(self) -> None:
        self.assertIn(SCENE_VIDEO, self.descriptor.capabilities)
        self.assertEqual(self.descriptor.billing_mode, "local")
        self.assertEqual(self.descriptor.estimated_unit_cost, 0.0)

    def test_it_never_outranks_a_real_footage_provider_by_accident(self) -> None:
        """The Director picks it per scene; blind routing must not prefer it."""
        gateway = build_scene_provider_gateway()
        stock = gateway.require("stock_footage").descriptor
        self.assertGreater(self.descriptor.priority, stock.priority)

    def test_a_money_ceiling_cannot_block_it(self) -> None:
        from youtube_monitor import main

        policy = {**main.settings.default_automation_policy(), "max_project_cost": 0.01}
        with mock.patch.object(main.settings, "automation_policy", return_value=policy):
            self.assertEqual(main._cost_budget_breach(1, "motion_graphics"), "")


if __name__ == "__main__":
    unittest.main()
