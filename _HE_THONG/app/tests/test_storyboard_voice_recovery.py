from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from youtube_monitor import main


APP_ROOT = Path(__file__).resolve().parent.parent


class StoryboardVoiceRecoveryUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = (APP_ROOT / "youtube_monitor" / "static" / "project-detail.js").read_text(encoding="utf-8")

    def test_normal_dialogue_cut_only_plans_source_cues(self) -> None:
        start = self.page.index("async function cutStudioScenesByDialogue()")
        end = self.page.index("async function planStudioSourceCues()", start)
        action = self.page[start:end]
        self.assertIn("timeline/plan-source-cues", action)
        self.assertNotIn("queueStudioProductionJob('source_visuals'", action)
        self.assertNotIn("timeline/from-dialogue", action)
        self.assertIn("Bấm “3. Cắt clip theo các mốc đã chọn”", action)

    def test_storyboard_can_restore_or_manually_attach_voice(self) -> None:
        self.assertIn("async function restoreStudioGeneratedVoices()", self.page)
        self.assertIn("timeline/reattach-voice", self.page)
        self.assertIn("async function uploadStudioVoiceForScene(segmentId)", self.page)
        self.assertIn("async function attachStudioGeneratedVoiceForScene(segmentId)", self.page)
        self.assertIn("voice-library", self.page)
        self.assertIn("attach-generated-voice", self.page)
        self.assertIn("/assets/upload", self.page)
        self.assertIn("/attach-asset", self.page)

    def test_storyboard_text_comes_from_the_same_timeline_field_as_voiceover(self) -> None:
        self.assertIn("const spokenText = String(segment?.voice_text || shot.narration || '').trim();", self.page)
        self.assertIn("esc(spokenText || 'Chưa có lời dẫn cho cảnh này.')", self.page)

    def test_voice_generation_automatically_syncs_stale_script_data(self) -> None:
        start = self.page.index("async function generateStudioVoiceover()")
        end = self.page.index("async function runStudioSceneBatch(", start)
        action = self.page[start:end]
        self.assertIn("Kịch bản mới hơn storyboard; đang đồng bộ", action)
        self.assertIn("Timeline cũ không khớp kịch bản; đang đồng bộ", action)
        self.assertNotIn("Đã dừng: storyboard hiện vẫn thuộc phiên bản kịch bản cũ", action)


class AttachGeneratedVoiceEndpointTests(unittest.TestCase):
    def test_selected_library_voice_is_attached_only_to_that_segment(self) -> None:
        with mock.patch.object(main.database, "get_project_timeline_segment", side_effect=[
            {"id": 41, "project_id": 7}, {"id": 41, "project_id": 7, "audio_path": "C:/voice.wav"},
        ]), mock.patch.object(main.database, "update_project_timeline_segment") as update, mock.patch.object(
            main.database, "resync_timeline_segment_states"
        ) as resync, mock.patch.object(main.voice_library, "index_voices", return_value={
            "voice-key": {"audio_path": "C:/voice.wav", "text": "hello"},
        }):
            result = main.attach_generated_voice_to_timeline(
                41, main.AttachGeneratedVoiceRequest(voice_key="voice-key")
            )

        update.assert_called_once_with(41, audio_path="C:/voice.wav")
        resync.assert_called_once_with(7)
        self.assertEqual(result["status"], "attached")


if __name__ == "__main__":
    unittest.main()
