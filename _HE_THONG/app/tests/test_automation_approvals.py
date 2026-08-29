"""A paused pipeline must be releasable from the page, not only by API.

`_automation_pause_active()` refuses to queue further media while an approval
is pending, so an approval the interface never shows — or shows without a
control — parks the pipeline permanently.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from youtube_monitor import main
from youtube_monitor.database import Database
from youtube_monitor.main import app

PAGE = Path(__file__).resolve().parent.parent / "youtube_monitor" / "templates" / "index.html"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_page_has_somewhere_to_show_pending_approvals(page: str) -> None:
    assert 'id="automationApprovals"' in page


def test_every_decision_the_api_accepts_has_a_control(page: str) -> None:
    for decision in ("approved", "changes_requested", "dismissed"):
        assert f"decideApproval({'${approval.id}'}, '{decision}')" in page


def test_the_decision_call_targets_the_real_endpoint(page: str) -> None:
    assert "/api/automation/approvals/${approvalId}/decision" in page


def test_a_blocking_approval_is_marked_apart_from_a_notice(page: str) -> None:
    """Running out of providers stops work; a publish prompt does not."""
    assert "BLOCKING_APPROVALS" in page
    assert "provider_exhausted" in page
    assert "budget_exceeded" in page


def test_the_resume_role_offered_matches_the_roles_the_api_accepts(page: str) -> None:
    for role in ("research", "script", "director", "media", "qc"):
        assert f'<option value="{role}">' in page or f'value="{role}"' in page


def test_approvals_are_rendered_whenever_status_is_refreshed(page: str) -> None:
    assert "renderAutomationApprovals(data);" in page


def test_a_running_pipeline_can_be_reopened_without_the_browser_that_started_it(page: str) -> None:
    """The id lived only in localStorage, so a run started elsewhere — another
    machine, another browser, the API — was invisible in the interface."""
    assert 'id="automationProjectPicker"' in page
    assert "loadAutomationProjectList" in page
    assert "openAutomationProject(this.value)" in page
    assert "/api/automation/projects'" in page


def _project_database(directory: str) -> tuple[Database, int]:
    database = Database(Path(directory) / "approvals.db")
    database.upsert_channel(
        {
            "youtube_channel_id": "UC0000000000000000000009",
            "channel_url": "https://www.youtube.com/channel/UC0000000000000000000009",
            "title": "Approval channel",
            "uploads_playlist_id": "UU0000000000000000000009",
        }
    )
    database.upsert_video(
        {
            "youtube_video_id": "video-approval-1",
            "youtube_channel_id": "UC0000000000000000000009",
            "video_url": "https://www.youtube.com/watch?v=video-approval-1",
            "title": "Approval source video",
            "metadata_hash": "hash-approval-1",
            "raw_payload": {},
        }
    )
    project = database.create_production_project("video-approval-1")
    return database, int(project["id"])


class ApprovalReleasesThePauseTests(unittest.TestCase):
    def test_deciding_an_approval_lets_the_pipeline_move_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            with mock.patch.object(main, "database", database):
                main._pause_for_automation_block(
                    project_id,
                    main.PROVIDER_EXHAUSTED_APPROVAL,
                    "Hết provider khả dụng",
                    {"detail": "gflow_not_logged_in"},
                )
                self.assertEqual(
                    main._automation_pause_active(project_id),
                    main.PROVIDER_EXHAUSTED_APPROVAL,
                )
                approval = database.list_automation_approvals(
                    project_id=project_id, status="pending"
                )[0]
                database.decide_automation_approval(
                    int(approval["id"]), "dismissed", "da dang nhap lai gflow"
                )
                self.assertEqual(main._automation_pause_active(project_id), "")

    def test_the_pending_approval_reaches_the_page_through_the_status_call(self) -> None:
        """The panel reads `approvals` off the bundled status response."""
        with tempfile.TemporaryDirectory() as directory:
            database, project_id = _project_database(directory)
            with mock.patch.object(main, "database", database):
                main._pause_for_automation_block(
                    project_id,
                    main.BUDGET_EXCEEDED_APPROVAL,
                    "Chi phí chạm hạn mức",
                    {"detail": "vuot han muc"},
                )
                with TestClient(app) as client:
                    body = client.get(f"/api/automation/projects/{project_id}").json()
            pending = [
                item for item in body["approvals"] if item["status"] == "pending"
            ]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["approval_type"], main.BUDGET_EXCEEDED_APPROVAL)
            self.assertEqual(pending[0]["payload"]["detail"], "vuot han muc")


if __name__ == "__main__":
    unittest.main()
