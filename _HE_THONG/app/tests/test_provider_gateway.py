from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from youtube_monitor.database import Database
from youtube_monitor.providers import (
    EXECUTION_EXTERNAL_SIDECAR,
    SCENE_IMAGE,
    SCENE_VIDEO,
    FunctionSceneProviderAdapter,
    ProviderDescriptor,
    ProviderGateway,
    ProviderGatewayError,
    SidecarSceneProviderAdapter,
)
from youtube_monitor.scene_generator import SceneGenerationWorker, build_scene_provider_gateway


class ProviderGatewayTests(unittest.TestCase):
    def test_gateway_delegates_to_registered_adapter(self):
        received = {}

        def generate(database, job, artifact_root):
            received.update(database=database, job=job, artifact_root=artifact_root)
            return str(artifact_root / "scene.png")

        gateway = ProviderGateway(
            [
                FunctionSceneProviderAdapter(
                    ProviderDescriptor("demo", "Demo", frozenset({SCENE_IMAGE})),
                    generate,
                )
            ]
        )
        database = object()
        root = Path("artifacts")

        output = gateway.execute_scene(
            " DEMO ",
            database,
            {"id": 7},
            root,
            capability=SCENE_IMAGE,
        )

        self.assertEqual(output, str(root / "scene.png"))
        self.assertIs(received["database"], database)
        self.assertEqual(received["job"], {"id": 7})
        self.assertEqual(received["artifact_root"], root)

    def test_duplicate_and_unknown_providers_have_actionable_errors(self):
        adapter = FunctionSceneProviderAdapter(
            ProviderDescriptor("demo", "Demo", frozenset({SCENE_IMAGE})),
            lambda database, job, root: "unused",
        )
        gateway = ProviderGateway([adapter])

        with self.assertRaisesRegex(ProviderGatewayError, "da duoc dang ky"):
            gateway.register(adapter)
        with self.assertRaisesRegex(ProviderGatewayError, "Provider da dang ky: demo"):
            gateway.require("missing")

    def test_external_sidecar_is_catalogued_but_not_executed_in_process(self):
        gateway = ProviderGateway(
            [
                SidecarSceneProviderAdapter(
                    ProviderDescriptor(
                        "browser_video",
                        "Browser Video",
                        frozenset({SCENE_VIDEO}),
                        execution_mode=EXECUTION_EXTERNAL_SIDECAR,
                    )
                )
            ]
        )

        self.assertEqual(
            gateway.provider_keys(execution_mode=EXECUTION_EXTERNAL_SIDECAR),
            ("browser_video",),
        )
        with self.assertRaisesRegex(ProviderGatewayError, "sidecar/web"):
            gateway.execute_scene(
                "browser_video",
                object(),
                {"id": 1},
                Path("artifacts"),
                capability=SCENE_VIDEO,
            )

    def test_default_catalog_contains_internal_and_external_scene_providers(self):
        gateway = build_scene_provider_gateway()
        expected_internal = {
            "runway",
            "openai_image",
            "gemini_image",
            "gemini_veo",
            "gflow_cli",
            "gflow_image",
        }

        self.assertTrue(expected_internal.issubset(set(gateway.provider_keys())))
        self.assertTrue(
            set(Database.EXTERNAL_SIDECAR_PROVIDERS).issubset(set(gateway.provider_keys()))
        )
        self.assertEqual(
            set(gateway.provider_keys(execution_mode=EXECUTION_EXTERNAL_SIDECAR)),
            set(Database.EXTERNAL_SIDECAR_PROVIDERS),
        )

    def test_scene_worker_uses_injected_gateway_instead_of_provider_if_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            database = _WorkerDatabase()
            gateway = ProviderGateway(
                [
                    FunctionSceneProviderAdapter(
                        ProviderDescriptor("custom", "Custom", frozenset({SCENE_IMAGE})),
                        lambda database, job, root: str(Path(directory) / "custom.png"),
                    )
                ]
            )
            worker = SceneGenerationWorker(database, Path(directory), provider_gateway=gateway)

            worker._process(91)

            self.assertEqual(database.finished["status"], "completed")
            self.assertTrue(database.finished["output_path"].endswith("custom.png"))

    def test_scene_worker_routes_to_bounded_fallback_after_provider_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            database = _FallbackWorkerDatabase()
            gateway = ProviderGateway(
                [
                    FunctionSceneProviderAdapter(
                        ProviderDescriptor("primary", "Primary", frozenset({SCENE_IMAGE})),
                        lambda _database, _job, _root: (_ for _ in ()).throw(RuntimeError("provider down")),
                    ),
                    FunctionSceneProviderAdapter(
                        ProviderDescriptor("backup", "Backup", frozenset({SCENE_IMAGE})),
                        lambda _database, _job, root: str(root / "backup.png"),
                    ),
                ]
            )
            worker = SceneGenerationWorker(database, Path(directory), provider_gateway=gateway)
            worker.set_failure_router(lambda _job, _error, _kind: "backup")

            worker._process(12)
            self.assertEqual(database.job["status"], "queued")
            self.assertEqual(database.job["provider"], "backup")
            worker._process(12)

            self.assertEqual(database.finished["status"], "completed")
            self.assertEqual(database.job["attempt_count"], 2)
            self.assertEqual([item["status"] for item in database.usage], ["failed", "estimated", "completed"])


class _WorkerDatabase:
    EXTERNAL_SIDECAR_PROVIDERS = ()

    def __init__(self):
        self.finished = {}

    def claim_scene_generation_job(self, job_id):
        return {
            "id": job_id,
            "project_id": 1,
            "timeline_segment_id": 2,
            "provider": "custom",
            "job_kind": "image",
            "prompt_written": 1,
        }

    def find_project_asset_by_path(self, project_id, output_path):
        return None

    def finish_scene_generation_job(self, job_id, status, **values):
        self.finished = {"job_id": job_id, "status": status, **values}
        return self.finished

    def finalize_scene_provider_usage(self, job_id, status, **values):
        return {"scene_job_id": job_id, "status": status, **values}

    def list_queued_scene_generation_job_ids(self, limit=20):
        return []


class _FallbackWorkerDatabase:
    EXTERNAL_SIDECAR_PROVIDERS = ()

    def __init__(self):
        self.job = {
            "id": 12,
            "project_id": 1,
            "timeline_segment_id": 2,
            "provider": "primary",
            "job_kind": "image",
            "prompt_written": 1,
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": 2,
        }
        self.finished = {}
        self.usage = []

    def claim_scene_generation_job(self, job_id):
        if job_id != self.job["id"] or self.job["status"] != "queued":
            return None
        self.job["status"] = "running"
        self.job["attempt_count"] += 1
        return dict(self.job)

    def find_project_asset_by_path(self, project_id, output_path):
        return None

    def finish_scene_generation_job(self, job_id, status, **values):
        self.job["status"] = status
        self.finished = {"job_id": job_id, "status": status, **values}
        return self.finished

    def finalize_scene_provider_usage(self, job_id, status, **values):
        item = {"scene_job_id": job_id, "provider": self.job["provider"], "status": status, **values}
        self.usage.append(item)
        return item

    def record_scene_provider_failure(self, provider, error):
        return {"provider": provider, "error": error}

    def reroute_scene_generation_job(self, job_id, provider, **_values):
        if self.job["attempt_count"] >= self.job["max_attempts"]:
            return None
        self.job["provider"] = provider
        self.job["status"] = "queued"
        return dict(self.job)

    def record_provider_usage(self, **values):
        self.usage.append(values)
        return values

    def list_queued_scene_generation_job_ids(self, limit=20):
        return []


if __name__ == "__main__":
    unittest.main()
