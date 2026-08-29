from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from youtube_monitor import main, settings
from youtube_monitor.database import Database
from youtube_monitor.providers import (
    SCENE_IMAGE,
    FunctionSceneProviderAdapter,
    ProviderDescriptor,
    ProviderGateway,
    ProviderGatewayError,
    ProviderRoutePolicy,
)


def _policy(**overrides: object) -> dict[str, object]:
    policy = settings.default_automation_policy()
    policy.update(overrides)
    return policy


def _project_database(directory: str) -> tuple[Database, int]:
    database = Database(Path(directory) / "policy.db")
    database.upsert_channel(
        {
            "youtube_channel_id": "UC0000000000000000000001",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000001",
            "title": "Policy channel",
            "uploads_playlist_id": "UU0000000000000000000001",
        }
    )
    database.upsert_video(
        {
            "youtube_video_id": "video-policy-1",
            "youtube_channel_id": "UC0000000000000000000001",
            "video_url": "https://www.youtube.com/watch?v=video-policy-1",
            "title": "Policy source video",
            "description": "",
            "metadata_hash": "hash-policy-1",
            "raw_payload": {},
        }
    )
    project = database.create_production_project("video-policy-1")
    assert project is not None
    return database, int(project["id"])


class AutomationPolicyCostSettingsTests(unittest.TestCase):
    def test_cost_ceilings_default_to_no_limit(self) -> None:
        policy = settings.default_automation_policy()
        self.assertEqual(policy["max_project_cost"], 0.0)
        self.assertEqual(policy["max_daily_cost"], 0.0)

    def test_saved_cost_ceilings_are_read_back(self) -> None:
        raw = json.dumps({"max_project_cost": 12.5, "max_daily_cost": 3})
        with mock.patch.object(settings, "integration_value", return_value=raw):
            policy = settings.automation_policy()
        self.assertEqual(policy["max_project_cost"], 12.5)
        self.assertEqual(policy["max_daily_cost"], 3.0)

    def test_negative_ceiling_is_ignored_rather_than_blocking_everything(self) -> None:
        raw = json.dumps({"max_project_cost": -5})
        with mock.patch.object(settings, "integration_value", return_value=raw):
            policy = settings.automation_policy()
        self.assertEqual(policy["max_project_cost"], 0.0)

    def test_unreadable_ceiling_falls_back_to_the_default(self) -> None:
        raw = json.dumps({"max_daily_cost": "nhiều"})
        with mock.patch.object(settings, "integration_value", return_value=raw):
            policy = settings.automation_policy()
        self.assertEqual(policy["max_daily_cost"], 0.0)


class SubscriptionRoutingPolicyTests(unittest.TestCase):
    def _gateway(self) -> ProviderGateway:
        return ProviderGateway(
            [
                FunctionSceneProviderAdapter(
                    ProviderDescriptor(
                        "sub_image",
                        "Subscription image",
                        frozenset({SCENE_IMAGE}),
                        billing_mode="subscription",
                    ),
                    lambda database, job, root: "sub.png",
                ),
                FunctionSceneProviderAdapter(
                    ProviderDescriptor(
                        "api_image",
                        "Paid API image",
                        frozenset({SCENE_IMAGE}),
                        billing_mode="api",
                        estimated_unit_cost=0.04,
                    ),
                    lambda database, job, root: "api.png",
                ),
            ]
        )

    def test_subscription_providers_are_rejected_when_the_user_turns_them_off(self) -> None:
        route = self._gateway().route(
            SCENE_IMAGE,
            policy=ProviderRoutePolicy(allow_subscription_billing=False),
        )
        self.assertEqual(route.selected.key, "api_image")
        rejected = {
            item["provider"]: item["reason"]
            for item in route.candidates
            if not item["eligible"]
        }
        self.assertEqual(rejected["sub_image"], "subscription_media_disabled")

    def test_turning_off_both_billing_modes_leaves_no_provider(self) -> None:
        with self.assertRaises(ProviderGatewayError) as ctx:
            self._gateway().route(
                SCENE_IMAGE,
                policy=ProviderRoutePolicy(
                    allow_subscription_billing=False,
                    allow_api_billing=False,
                ),
            )
        self.assertIn("subscription_media_disabled", str(ctx.exception))
        self.assertIn("paid_api_disabled", str(ctx.exception))

    def test_subscription_stays_available_by_default(self) -> None:
        route = self._gateway().route(SCENE_IMAGE)
        self.assertEqual(route.selected.key, "sub_image")


class ProviderCostLedgerTests(unittest.TestCase):
    def test_project_cost_counts_the_larger_of_estimated_and_actual(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            database.record_provider_usage(
                provider="api_image",
                capability=SCENE_IMAGE,
                status="estimated",
                project_id=project_id,
                estimated_cost=0.5,
            )
            database.record_provider_usage(
                provider="api_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=project_id,
                estimated_cost=0.5,
                actual_cost=0.9,
            )
            self.assertAlmostEqual(database.project_provider_cost(project_id), 1.4)

    def test_a_cancelled_request_does_not_eat_the_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            database.record_provider_usage(
                provider="api_image",
                capability=SCENE_IMAGE,
                status="cancelled",
                project_id=project_id,
                estimated_cost=7.0,
            )
            self.assertEqual(database.project_provider_cost(project_id), 0.0)

    def test_today_cost_sees_a_row_written_now(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            before = database.today_provider_cost()
            database.record_provider_usage(
                provider="api_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=project_id,
                actual_cost=2.0,
            )
            self.assertAlmostEqual(database.today_provider_cost(), before + 2.0)

    def test_yesterdays_spending_does_not_count_against_today(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            usage = database.record_provider_usage(
                provider="api_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=project_id,
                actual_cost=4.0,
            )
            with database._connect() as connection:
                connection.execute(
                    "UPDATE provider_usage_ledger SET created_at = ? WHERE id = ?",
                    ("2020-01-01T00:00:00+00:00", int(usage["id"])),
                )
            self.assertEqual(database.today_provider_cost(), 0.0)
            self.assertAlmostEqual(database.project_provider_cost(project_id), 4.0)


class CostBudgetEnforcementTests(unittest.TestCase):
    def test_no_ceiling_means_no_block(self) -> None:
        with mock.patch.object(settings, "automation_policy", return_value=_policy()):
            self.assertEqual(main._cost_budget_breach(1, "openai_image"), "")

    def test_a_free_provider_is_never_blocked_by_a_spending_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            database.record_provider_usage(
                provider="openai_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=project_id,
                actual_cost=99.0,
            )
            policy = _policy(max_project_cost=1.0)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    # gflow_image runs on a subscription already paid for, so
                    # it adds nothing to the ledger's money total.
                    self.assertEqual(
                        main._cost_budget_breach(project_id, "gflow_image"), ""
                    )

    def test_a_paid_provider_is_blocked_once_the_project_ceiling_is_reached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            database.record_provider_usage(
                provider="openai_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=project_id,
                actual_cost=5.0,
            )
            descriptor = main.scene_provider_gateway.require("openai_image").descriptor
            paid = ProviderDescriptor(
                descriptor.key,
                descriptor.display_name,
                descriptor.capabilities,
                billing_mode="api",
                estimated_unit_cost=1.0,
            )
            policy = _policy(max_project_cost=5.5)
            adapter = mock.Mock(descriptor=paid)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(
                        main.scene_provider_gateway, "require", return_value=adapter
                    ):
                        breach = main._cost_budget_breach(project_id, "openai_image")
            self.assertIn("5.5", breach)
            self.assertIn("vượt hạn mức", breach)

    def test_the_daily_ceiling_applies_across_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            database.record_provider_usage(
                provider="openai_image",
                capability=SCENE_IMAGE,
                status="completed",
                project_id=None,
                actual_cost=9.0,
            )
            paid = ProviderDescriptor(
                "openai_image",
                "OpenAI Image API",
                frozenset({SCENE_IMAGE}),
                billing_mode="api",
                estimated_unit_cost=2.0,
            )
            policy = _policy(max_daily_cost=10.0)
            adapter = mock.Mock(descriptor=paid)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(
                        main.scene_provider_gateway, "require", return_value=adapter
                    ):
                        breach = main._cost_budget_breach(project_id, "openai_image")
            self.assertIn("mỗi ngày", breach)


class BatchCostCeilingTests(unittest.TestCase):
    """A ceiling has to stop a batch part-way, not only reject the first call."""

    def _project_with_three_scenes(self, directory: str) -> tuple[Database, int]:
        database = Database(Path(directory) / "batch.db")
        database.upsert_channel(
            {
                "youtube_channel_id": "UC0000000000000000000002",
                "channel_url": "https://www.youtube.com/channel/UC0000000000000000000002",
                "title": "Batch channel",
                "uploads_playlist_id": "UU0000000000000000000002",
            }
        )
        database.upsert_video(
            {
                "youtube_video_id": "video-batch-1",
                "youtube_channel_id": "UC0000000000000000000002",
                "video_url": "https://www.youtube.com/watch?v=video-batch-1",
                "title": "Batch source video",
                "metadata_hash": "hash-batch-1",
                "raw_payload": {},
            }
        )
        project = database.create_production_project("video-batch-1")
        script = database.create_project_script(project["id"], script_title="Batch script")
        database.create_project_timeline(
            project["id"],
            script["id"],
            [
                {
                    "segment_index": index,
                    "voice_text": f"Narration {index}",
                    "subtitle_text": f"Narration {index}",
                    "visual_prompt": f"A cinematic shot number {index}",
                    "duration_seconds": 5,
                }
                for index in range(1, 4)
            ],
        )
        return database, int(project["id"])

    def test_batch_stops_at_the_scene_that_would_cross_the_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = self._project_with_three_scenes(directory)
            # openai_image is estimated at $0.04 a scene, so $0.10 pays for
            # two scenes and stops before the third.
            policy = _policy(allow_paid_apis=True, max_project_cost=0.10)
            request = main.BatchSceneGenerationRequest(
                providers=["openai_image"], confirmed=True
            )
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(
                    settings, "openai_config", return_value=("test-key", "gpt-image-1")
                ):
                    with mock.patch.object(main, "database", database):
                        with mock.patch.object(main.scene_generation_worker, "enqueue"):
                            result = main.queue_scene_generation_batch(project_id, request)
            self.assertEqual(result["queued_count"], 2)
            self.assertIn("vượt hạn mức", result["budget_stop"])
            self.assertAlmostEqual(database.project_provider_cost(project_id), 0.08)

    def test_a_batch_under_the_ceiling_runs_every_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = self._project_with_three_scenes(directory)
            policy = _policy(allow_paid_apis=True, max_project_cost=5.0)
            request = main.BatchSceneGenerationRequest(
                providers=["openai_image"], confirmed=True
            )
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(
                    settings, "openai_config", return_value=("test-key", "gpt-image-1")
                ):
                    with mock.patch.object(main, "database", database):
                        with mock.patch.object(main.scene_generation_worker, "enqueue"):
                            result = main.queue_scene_generation_batch(project_id, request)
            self.assertEqual(result["queued_count"], 3)
            self.assertEqual(result["budget_stop"], "")

    def test_a_subscription_batch_ignores_the_money_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = self._project_with_three_scenes(directory)
            policy = _policy(max_project_cost=0.01)
            request = main.BatchSceneGenerationRequest(
                providers=["flow_image"], confirmed=True
            )
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(main.scene_generation_worker, "enqueue"):
                        result = main.queue_scene_generation_batch(project_id, request)
            self.assertEqual(result["queued_count"], 3)
            self.assertEqual(result["budget_stop"], "")


class ProviderCatalogCostTests(unittest.TestCase):
    def test_every_provider_declares_what_a_scene_costs(self) -> None:
        """An unknown cost silently disables the ceiling, so none may be None."""
        missing = [
            descriptor.key
            for descriptor in main.scene_provider_gateway.descriptors()
            if descriptor.estimated_unit_cost is None
        ]
        self.assertEqual(missing, [])

    def test_subscription_and_local_providers_cost_nothing_extra(self) -> None:
        for descriptor in main.scene_provider_gateway.descriptors():
            if descriptor.billing_mode in {"subscription", "local"}:
                self.assertEqual(
                    descriptor.estimated_unit_cost, 0.0, f"{descriptor.key} nên là 0"
                )

    def test_paid_api_providers_declare_a_positive_cost(self) -> None:
        for descriptor in main.scene_provider_gateway.descriptors():
            if descriptor.billing_mode == "api":
                self.assertGreater(
                    float(descriptor.estimated_unit_cost or 0),
                    0,
                    f"{descriptor.key} phải có chi phí ước tính",
                )


class BillingPolicyGateTests(unittest.TestCase):
    def test_paid_api_stays_blocked_by_default(self) -> None:
        with mock.patch.object(settings, "automation_policy", return_value=_policy()):
            with self.assertRaises(HTTPException) as ctx:
                main._enforce_provider_billing_policy("openai_image")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("API trả phí", ctx.exception.detail)

    def test_subscription_provider_is_blocked_when_the_policy_says_so(self) -> None:
        policy = _policy(allow_subscription_media=False)
        with mock.patch.object(settings, "automation_policy", return_value=policy):
            with self.assertRaises(HTTPException) as ctx:
                main._enforce_provider_billing_policy("gflow_image")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("gói thuê bao", ctx.exception.detail)

    def test_subscription_provider_passes_under_the_default_policy(self) -> None:
        with mock.patch.object(settings, "automation_policy", return_value=_policy()):
            main._enforce_provider_billing_policy("gflow_image")

    def test_route_policy_mirrors_both_saved_billing_switches(self) -> None:
        policy = _policy(allow_paid_apis=True, allow_subscription_media=False)
        with mock.patch.object(settings, "automation_policy", return_value=policy):
            route_policy = main._billing_route_policy()
        self.assertTrue(route_policy.allow_api_billing)
        self.assertFalse(route_policy.allow_subscription_billing)


class SceneReviewThresholdTests(unittest.TestCase):
    def test_threshold_follows_the_saved_policy(self) -> None:
        policy = _policy(min_scene_qc_score=9)
        with mock.patch.object(settings, "automation_policy", return_value=policy):
            self.assertEqual(main._scene_review_pass_score(), 9)

    def test_an_unreadable_threshold_falls_back_to_the_builtin_default(self) -> None:
        policy = _policy(min_scene_qc_score="cao")
        with mock.patch.object(settings, "automation_policy", return_value=policy):
            self.assertEqual(main._scene_review_pass_score(), main._REVIEW_PASS_SCORE)

    def test_threshold_is_clamped_to_the_ten_point_scale(self) -> None:
        policy = _policy(min_scene_qc_score=42)
        with mock.patch.object(settings, "automation_policy", return_value=policy):
            self.assertEqual(main._scene_review_pass_score(), 10)


class ProviderExhaustionPauseTests(unittest.TestCase):
    def _job(self, project_id: int) -> dict[str, object]:
        return {
            "id": 4321,
            "project_id": project_id,
            "provider": "gflow_image",
            "job_kind": "image",
        }

    def test_exhausted_providers_pause_the_pipeline_for_a_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            policy = _policy(pause_on_provider_exhaustion=True)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(
                        main.scene_provider_gateway,
                        "route",
                        side_effect=ProviderGatewayError("het provider"),
                    ):
                        fallback = main._route_scene_failure(
                            self._job(project_id), "quota", "provider"
                        )
            self.assertIsNone(fallback)
            approvals = database.list_automation_approvals(
                project_id=project_id, status="pending"
            )
            self.assertEqual(
                [item["approval_type"] for item in approvals],
                [main.PROVIDER_EXHAUSTED_APPROVAL],
            )
            self.assertEqual(approvals[0]["payload"]["failed_provider"], "gflow_image")

    def test_repeated_failures_raise_one_question_not_a_queue_of_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            policy = _policy(pause_on_provider_exhaustion=True)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(
                        main.scene_provider_gateway,
                        "route",
                        side_effect=ProviderGatewayError("het provider"),
                    ):
                        for _ in range(3):
                            main._route_scene_failure(
                                self._job(project_id), "quota", "provider"
                            )
            approvals = database.list_automation_approvals(
                project_id=project_id, status="pending"
            )
            self.assertEqual(len(approvals), 1)

    def test_the_pause_can_be_switched_off(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            policy = _policy(pause_on_provider_exhaustion=False)
            with mock.patch.object(settings, "automation_policy", return_value=policy):
                with mock.patch.object(main, "database", database):
                    with mock.patch.object(
                        main.scene_provider_gateway,
                        "route",
                        side_effect=ProviderGatewayError("het provider"),
                    ):
                        main._route_scene_failure(
                            self._job(project_id), "quota", "provider"
                        )
            self.assertEqual(
                database.list_automation_approvals(
                    project_id=project_id, status="pending"
                ),
                [],
            )

    def test_a_decided_approval_stops_holding_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            with mock.patch.object(main, "database", database):
                main._pause_for_automation_block(
                    project_id,
                    main.BUDGET_EXCEEDED_APPROVAL,
                    "Chi phí chạm hạn mức",
                    {"detail": "test"},
                )
                self.assertEqual(
                    main._automation_pause_active(project_id),
                    main.BUDGET_EXCEEDED_APPROVAL,
                )
                approval = database.list_automation_approvals(
                    project_id=project_id, status="pending"
                )[0]
                database.decide_automation_approval(
                    int(approval["id"]), "approved", "đã nâng hạn mức"
                )
                self.assertEqual(main._automation_pause_active(project_id), "")


if __name__ == "__main__":
    unittest.main()
