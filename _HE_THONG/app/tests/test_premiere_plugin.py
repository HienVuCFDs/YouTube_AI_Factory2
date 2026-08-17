from __future__ import annotations

import json
import unittest
from pathlib import Path


SYSTEM_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = SYSTEM_ROOT / "premiere_plugin"


class PremierePluginScaffoldTests(unittest.TestCase):
    def test_manifest_declares_premiere_uxp_panel_and_request_permission(self):
        manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifestVersion"], 5)
        self.assertEqual(manifest["host"]["app"], "premierepro")
        self.assertEqual(manifest["host"]["minVersion"], "25.6.0")
        self.assertEqual(manifest["requiredPermissions"]["localFileSystem"], "request")
        self.assertEqual(manifest["entrypoints"][0]["type"], "panel")

    def test_plugin_contains_auto_draft_actions(self):
        source = (PLUGIN_ROOT / "index.js").read_text(encoding="utf-8")
        for expected in (
            "Project.getActiveProject",
            "project.importFiles",
            "createSequenceFromMedia",
            "createOverwriteItemAction",
            "createSetEndAction",
            "createAddMarkerAction",
        ):
            self.assertIn(expected, source)
