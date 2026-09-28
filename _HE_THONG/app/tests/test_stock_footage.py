from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from youtube_monitor import stock_footage
from youtube_monitor.providers import SCENE_VIDEO, ProviderRoutePolicy
from youtube_monitor.scene_generator import build_scene_provider_gateway
from youtube_monitor.stock_footage import (
    ARCHIVE_ORG,
    NASA,
    StockClip,
    StockFootageError,
    _record_attribution,
    _target_size,
    generate_stock_footage_scene,
    rank_clips,
    search_keywords,
    search_stock_clips,
)


def _clip(title: str, source: str = ARCHIVE_ORG, size: int = 1000) -> StockClip:
    return StockClip(
        source=source,
        clip_id=f"{source}/{title}",
        title=title,
        page_url="https://example.invalid/page",
        download_url="https://example.invalid/clip.mp4",
        duration_seconds=30.0,
        size_bytes=size,
        license="public-domain",
        attribution=f"{source} — {title}",
    )


class SearchKeywordTests(unittest.TestCase):
    def test_style_words_are_dropped_so_the_archive_can_match_a_subject(self) -> None:
        prompt = "A cinematic wide shot, 4k photorealistic, of a steam locomotive crossing a bridge"
        self.assertEqual(search_keywords(prompt, maximum=4), "steam locomotive crossing bridge")

    def test_a_repeated_word_is_only_used_once(self) -> None:
        self.assertEqual(search_keywords("city city city lights", maximum=6), "city lights")

    def test_the_word_budget_is_respected(self) -> None:
        keywords = search_keywords("alpha bravo charlie delta echo foxtrot golf", maximum=3)
        self.assertEqual(len(keywords.split()), 3)

    def test_a_prompt_of_pure_style_yields_nothing_rather_than_noise(self) -> None:
        self.assertEqual(search_keywords("cinematic photorealistic 4k bokeh"), "")


class RankingTests(unittest.TestCase):
    def test_the_closest_title_comes_first(self) -> None:
        clips = [_clip("Wholesome Meat Inspection"), _clip("Earth Rise Seen From Orbit", source=NASA)]
        ranked = rank_clips(clips, "Earth seen from orbit at night")
        self.assertEqual(ranked[0].title, "Earth Rise Seen From Orbit")

    def test_size_breaks_a_tie_so_the_order_is_stable(self) -> None:
        clips = [_clip("Harbour Boats", size=10), _clip("Harbour Boats", size=900)]
        self.assertEqual(rank_clips(clips, "harbour boats")[0].size_bytes, 900)

    def test_an_unmatchable_prompt_leaves_the_order_untouched(self) -> None:
        clips = [_clip("First"), _clip("Second")]
        self.assertEqual([c.title for c in rank_clips(clips, "cinematic 4k")], ["First", "Second"])


class TargetSizeTests(unittest.TestCase):
    def test_reads_both_written_forms(self) -> None:
        self.assertEqual(_target_size("1920:1080"), (1920, 1080))
        self.assertEqual(_target_size("1920x1080"), (1920, 1080))

    def test_falls_back_when_the_ratio_is_unusable(self) -> None:
        for value in ("", "abc", "0:0", "-4:3"):
            self.assertEqual(_target_size(value), (1280, 720))

    def test_odd_dimensions_are_evened_out_for_the_encoder(self) -> None:
        self.assertEqual(_target_size("1281:721"), (1280, 720))


class QueryWideningTests(unittest.TestCase):
    def test_a_query_is_widened_until_an_archive_answers(self) -> None:
        seen: list[str] = []

        def fake_archive(client, query, limit):
            seen.append(query)
            return [_clip("Harbour At Dawn")] if len(query.split()) <= 2 else []

        with mock.patch.object(stock_footage, "_search_archive_org", side_effect=fake_archive):
            with mock.patch.object(stock_footage, "_search_nasa", return_value=[]):
                clips = search_stock_clips(
                    "A steam locomotive crossing a tall iron bridge at dawn",
                    client=mock.Mock(),
                )
        self.assertEqual(len(clips), 1)
        self.assertEqual([len(query.split()) for query in seen], [6, 4, 2])

    def test_nothing_anywhere_returns_an_empty_list_not_an_error(self) -> None:
        with mock.patch.object(stock_footage, "_search_archive_org", return_value=[]):
            with mock.patch.object(stock_footage, "_search_nasa", return_value=[]):
                self.assertEqual(search_stock_clips("harbour boats", client=mock.Mock()), [])

    def test_a_prompt_with_no_usable_word_never_calls_an_archive(self) -> None:
        archive = mock.Mock(return_value=[])
        with mock.patch.object(stock_footage, "_search_archive_org", archive):
            with mock.patch.object(stock_footage, "_search_nasa", return_value=[]):
                self.assertEqual(search_stock_clips("cinematic 4k bokeh", client=mock.Mock()), [])
        archive.assert_not_called()


class DownloadGuardTests(unittest.TestCase):
    def _client_declaring(self, length: int, body: bytes = b"") -> mock.Mock:
        response = mock.MagicMock()
        response.headers = {"content-length": str(length)}
        response.raise_for_status = mock.Mock()
        response.iter_bytes = mock.Mock(return_value=iter([body] if body else []))
        stream = mock.MagicMock()
        stream.__enter__ = mock.Mock(return_value=response)
        stream.__exit__ = mock.Mock(return_value=False)
        client = mock.Mock()
        client.stream = mock.Mock(return_value=stream)
        return client

    def test_a_declared_oversize_file_is_refused_before_any_byte_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clip.source"
            client = self._client_declaring(stock_footage.MAX_DOWNLOAD_BYTES + 1)
            with self.assertRaises(StockFootageError) as ctx:
                stock_footage._download(client, _clip("Big"), destination)
            self.assertIn("gioi han tai ve", str(ctx.exception))
            self.assertFalse(destination.exists())

    def test_a_file_that_lies_about_its_size_is_cut_off_mid_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clip.source"
            oversize = b"x" * (stock_footage.MAX_DOWNLOAD_BYTES + 8)
            client = self._client_declaring(0, oversize)
            with self.assertRaises(StockFootageError):
                stock_footage._download(client, _clip("Liar"), destination)
            self.assertFalse(destination.exists())

    def test_an_empty_download_is_treated_as_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clip.source"
            client = self._client_declaring(0)
            with self.assertRaises(StockFootageError) as ctx:
                stock_footage._download(client, _clip("Empty"), destination)
            self.assertIn("rong", str(ctx.exception))

    def test_a_transport_error_is_reported_as_a_stock_footage_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = mock.Mock()
            client.stream = mock.Mock(side_effect=httpx.ConnectError("khong noi duoc"))
            with self.assertRaises(StockFootageError):
                stock_footage._download(client, _clip("Gone"), Path(directory) / "clip.source")


class AttributionTests(unittest.TestCase):
    def test_every_clip_used_keeps_its_credit_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _record_attribution(root, root / "one.mp4", _clip("First Film"))
            manifest = _record_attribution(root, root / "two.mp4", _clip("Second Film", source=NASA))
            entries = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(sorted(entries), ["one.mp4", "two.mp4"])
            self.assertEqual(entries["two.mp4"]["source"], NASA)
            self.assertEqual(entries["one.mp4"]["license"], "public-domain")

    def test_reusing_a_name_replaces_its_entry_instead_of_duplicating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _record_attribution(root, root / "one.mp4", _clip("Old"))
            manifest = _record_attribution(root, root / "one.mp4", _clip("New"))
            entries = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries["one.mp4"]["title"], "New")

    def test_a_corrupt_manifest_is_rebuilt_rather_than_crashing_the_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "NGUON_FOOTAGE.json").write_text("{ khong phai json", encoding="utf-8")
            manifest = _record_attribution(root, root / "one.mp4", _clip("Fresh"))
            self.assertEqual(list(json.loads(manifest.read_text(encoding="utf-8"))), ["one.mp4"])


class GenerateSceneTests(unittest.TestCase):
    def _job(self) -> dict[str, object]:
        return {
            "id": 42,
            "project_id": 7,
            "timeline_segment_id": 3,
            "prompt": "A steam locomotive crossing a bridge",
            "duration_seconds": 5,
            "ratio": "1280:720",
        }

    def test_an_empty_prompt_is_refused_before_any_network_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = {**self._job(), "prompt": "   "}
            with self.assertRaises(StockFootageError):
                generate_stock_footage_scene(None, job, Path(directory), client=mock.Mock())

    def test_finding_nothing_names_the_keywords_that_were_tried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(stock_footage, "search_stock_clips", return_value=[]):
                with self.assertRaises(StockFootageError) as ctx:
                    generate_stock_footage_scene(
                        None, self._job(), Path(directory), client=mock.Mock()
                    )
        self.assertIn("steam locomotive", str(ctx.exception))

    def test_a_finished_scene_returns_its_path_and_records_where_it_came_from(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def fake_cut(source_path, output_path, **_):
                output_path.write_bytes(b"mp4-bytes")

            with mock.patch.object(
                stock_footage, "search_stock_clips", return_value=[_clip("Steam Locomotive")]
            ):
                with mock.patch.object(stock_footage, "_download", side_effect=lambda c, clip, dest: dest):
                    with mock.patch.object(stock_footage, "_cut_scene_clip", side_effect=fake_cut):
                        output = generate_stock_footage_scene(
                            None, self._job(), Path(directory), client=mock.Mock()
                        )
            path = Path(output)
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "stock-segment-3-job-42.mp4")
            manifest = json.loads(
                (path.parent.parent.parent / "NGUON_FOOTAGE.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest[path.name]["license"], "public-domain")

    def test_one_unusable_archive_file_does_not_lose_the_scene(self) -> None:
        """A short or broken film must not end the scene while others remain."""
        with tempfile.TemporaryDirectory() as directory:
            attempts: list[str] = []

            def fake_cut(source_path, output_path, **_):
                attempts.append(source_path.name)
                if len(attempts) == 1:
                    raise StockFootageError("Clip nguon qua ngan")
                output_path.write_bytes(b"mp4-bytes")

            candidates = [_clip("Too Short"), _clip("Steam Locomotive Crossing")]
            with mock.patch.object(stock_footage, "search_stock_clips", return_value=candidates):
                with mock.patch.object(stock_footage, "_download", side_effect=lambda c, clip, dest: dest):
                    with mock.patch.object(stock_footage, "_cut_scene_clip", side_effect=fake_cut):
                        output = generate_stock_footage_scene(
                            None, self._job(), Path(directory), client=mock.Mock()
                        )
            self.assertEqual(len(attempts), 2)
            self.assertTrue(Path(output).is_file())

    def test_when_every_candidate_fails_the_reasons_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                stock_footage, "search_stock_clips", return_value=[_clip("Broken")]
            ):
                with mock.patch.object(stock_footage, "_download", side_effect=lambda c, clip, dest: dest):
                    with mock.patch.object(
                        stock_footage,
                        "_cut_scene_clip",
                        side_effect=StockFootageError("Clip nguon qua ngan"),
                    ):
                        with self.assertRaises(StockFootageError) as ctx:
                            generate_stock_footage_scene(
                                None, self._job(), Path(directory), client=mock.Mock()
                            )
            self.assertIn("Clip nguon qua ngan", str(ctx.exception))

    def test_the_downloaded_original_is_not_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def fake_download(client, clip, destination):
                destination.write_bytes(b"source-bytes")
                return destination

            def fake_cut(source_path, output_path, **_):
                output_path.write_bytes(b"mp4-bytes")

            with mock.patch.object(
                stock_footage, "search_stock_clips", return_value=[_clip("Steam")]
            ):
                with mock.patch.object(stock_footage, "_download", side_effect=fake_download):
                    with mock.patch.object(stock_footage, "_cut_scene_clip", side_effect=fake_cut):
                        output = generate_stock_footage_scene(
                            None, self._job(), Path(directory), client=mock.Mock()
                        )
            leftovers = list(Path(output).parent.glob("*.source"))
            self.assertEqual(leftovers, [])


class StockProviderRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = build_scene_provider_gateway()

    def test_the_provider_is_registered_as_a_free_local_video_source(self) -> None:
        descriptor = self.gateway.require("stock_footage").descriptor
        self.assertIn(SCENE_VIDEO, descriptor.capabilities)
        self.assertEqual(descriptor.billing_mode, "local")
        self.assertEqual(descriptor.estimated_unit_cost, 0.0)

    def test_flow_is_still_preferred_while_it_works(self) -> None:
        route = self.gateway.route(
            SCENE_VIDEO, policy=ProviderRoutePolicy(allow_api_billing=False)
        )
        self.assertEqual(route.selected.key, "gflow_cli")

    def test_it_takes_over_when_every_paid_video_route_is_out(self) -> None:
        states = {
            "gflow_cli": {"available": False, "reason": "gflow_not_logged_in"},
            "phantom_canvas_video": {"available": False, "reason": "phantom_canvas_not_running"},
            "flow_veo": {"available": False, "reason": "browser_extension_not_connected"},
        }
        route = self.gateway.route(
            SCENE_VIDEO,
            provider_states=states,
            policy=ProviderRoutePolicy(allow_api_billing=False),
        )
        self.assertEqual(route.selected.key, "stock_footage")

    def test_a_money_ceiling_cannot_block_it(self) -> None:
        """It spends nothing, so a spending ceiling has no claim on it."""
        from youtube_monitor import main

        with mock.patch.object(main.settings, "automation_policy", return_value={
            **main.settings.default_automation_policy(), "max_project_cost": 0.01,
        }):
            self.assertEqual(main._cost_budget_breach(1, "stock_footage"), "")


if __name__ == "__main__":
    unittest.main()
