"""One signed-in account per channel, not one for the whole app.

A creator has several channels, usually not all on one Google account, and
the app already models that: every channel names its platform and group, and
every publication names its channel. Only the sign-in was singular - one
token file and a `get_access_token()` with nothing to say which account it
meant - so whichever account was linked last received every upload. A video
on the wrong channel is not something this app can take back.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.ui_source import studio_ui
from youtube_monitor import oauth


def _token(refresh: str = "r-1", expires_in: float = 3600.0) -> dict:
    return {
        "access_token": f"access-for-{refresh}",
        "refresh_token": refresh,
        "expires_at": time.time() + expires_in,
        "scope": "youtube.upload",
    }


class TokensAreFiledUnderTheirChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patcher = mock.patch.object(oauth, "OAUTH_TOKEN_PATH", self.root / "oauth_token.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, channel_id: int | None, token: dict) -> None:
        path = oauth.token_path(channel_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(token), encoding="utf-8")

    def test_each_channel_gets_its_own_file(self) -> None:
        self.assertNotEqual(oauth.token_path(1), oauth.token_path(2))
        self.assertEqual(oauth.token_path(None), oauth.OAUTH_TOKEN_PATH)

    def test_two_channels_use_two_accounts(self) -> None:
        """The whole point: an upload for channel 2 must not use channel 1."""
        self._write(1, _token("refresh-one"))
        self._write(2, _token("refresh-two"))

        self.assertEqual(oauth.get_access_token(1), "access-for-refresh-one")
        self.assertEqual(oauth.get_access_token(2), "access-for-refresh-two")

    def test_a_channel_with_no_account_of_its_own_uses_the_app_wide_one(self) -> None:
        """So a setup that already works keeps working."""
        self._write(None, _token("shared"))

        self.assertEqual(oauth.get_access_token(7), "access-for-shared")
        self.assertFalse(oauth.has_own_token(7))

    def test_its_own_account_wins_over_the_shared_one(self) -> None:
        self._write(None, _token("shared"))
        self._write(3, _token("its-own"))

        self.assertEqual(oauth.get_access_token(3), "access-for-its-own")
        self.assertTrue(oauth.has_own_token(3))

    def test_signing_one_channel_out_leaves_the_others_alone(self) -> None:
        self._write(1, _token("one"))
        self._write(2, _token("two"))

        oauth.disconnect(1)

        self.assertFalse(oauth.token_path(1).exists())
        self.assertTrue(oauth.token_path(2).exists())

    def test_an_unlinked_channel_with_no_shared_account_is_refused(self) -> None:
        with self.assertRaises(oauth.OAuthError) as caught:
            oauth.get_access_token(9)

        self.assertIn("chưa đăng nhập", str(caught.exception))

    def test_status_answers_about_the_channel_it_was_asked_about(self) -> None:
        self._write(1, _token("one"))

        self.assertTrue(oauth.status(1)["connected"])
        self.assertTrue(oauth.status(1)["own_account"])
        self.assertFalse(oauth.status(2)["connected"])

    def test_status_says_when_a_channel_is_borrowing_the_shared_account(self) -> None:
        """Two channels posting to one account should not look like two."""
        self._write(None, _token("shared"))

        answer = oauth.status(5)

        self.assertTrue(answer["connected"])
        self.assertFalse(answer["own_account"])


class TheSignInRoundTripCarriesTheChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = mock.patch.object(
            oauth, "OAUTH_TOKEN_PATH", Path(directory.name) / "oauth_token.json"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_callback_knows_which_channel_was_being_linked(self) -> None:
        """Google hands back only the state; it has to carry the channel."""
        oauth._save_state("abc", 4)

        valid, channel_id = oauth._consume_state("abc")

        self.assertTrue(valid)
        self.assertEqual(channel_id, 4)

    def test_a_stale_or_wrong_state_is_refused(self) -> None:
        oauth._save_state("abc", 4)

        self.assertEqual(oauth._consume_state("wrong"), (False, None))

    def test_the_app_wide_sign_in_carries_no_channel(self) -> None:
        oauth._save_state("abc")

        self.assertEqual(oauth._consume_state("abc"), (True, None))

    def test_google_is_asked_to_offer_the_account_chooser(self) -> None:
        """Otherwise it reuses the browser's current account, and the second
        channel silently links to the first one's."""
        with mock.patch.object(oauth, "_oauth_config", return_value=("id", "secret", "http://x/cb")):
            url = oauth.build_authorize_url(2)

        self.assertIn("prompt=select_account", url)


class ItIsWiredThroughToTheUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent / "youtube_monitor"
        self.publisher = (root / "publisher.py").read_text(encoding="utf-8")
        self.main = (root / "main.py").read_text(encoding="utf-8")
        self.page = studio_ui()

    def test_the_upload_uses_the_publications_own_channel(self) -> None:
        self.assertIn('channel_id = publication.get("managed_channel_id")', self.publisher)
        self.assertIn("get_access_token(int(channel_id) if channel_id else None)", self.publisher)

    def test_the_gate_asks_about_that_channel_too(self) -> None:
        """"Someone is signed in" says nothing about whether this one is."""
        self.assertIn("oauth_status(managed_channel_id).get(\"connected\")", self.main)

    def test_the_routes_accept_a_channel(self) -> None:
        from youtube_monitor.main import app

        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/oauth/youtube/authorize", paths)
        self.assertIn("/api/oauth/youtube/status", paths)

    def test_the_dialog_can_sign_a_channel_in(self) -> None:
        self.assertIn("connectChannelAccount()", self.page)
        self.assertIn("managed_channel_id=${selected}", self.page)

    def test_the_picker_shows_which_channels_are_signed_in(self) -> None:
        self.assertIn("state.channelAccounts", self.page)
        self.assertIn("chưa đăng nhập", self.page)


class VerifyingWhereAChannelActuallyPostsTests(unittest.TestCase):
    """Signed in is not the same as signed in to the right channel.

    A Google account can own several YouTube channels, and the consent flow
    asks which one. Without checking per managed channel there is no way to
    see that a video will land where it was meant to - only that somebody
    somewhere is authorised.
    """

    def setUp(self) -> None:
        root = Path(__file__).resolve().parent.parent / "youtube_monitor"
        self.publisher = (root / "publisher.py").read_text(encoding="utf-8")
        self.routes = (root / "api" / "routes_oauth.py").read_text(encoding="utf-8")

    def test_the_listing_asks_for_one_channels_account(self) -> None:
        self.assertIn(
            "def list_authorized_channels(\n        self, managed_channel_id: int | None = None",
            self.publisher,
        )
        self.assertIn("get_access_token(managed_channel_id)", self.publisher)

    def test_the_route_passes_the_channel_through(self) -> None:
        self.assertIn("list_authorized_channels(managed_channel_id)", self.routes)

    def test_the_answer_says_which_channel_it_is_about(self) -> None:
        """Otherwise two answers look identical and cannot be told apart."""
        self.assertIn('"managed_channel_id": managed_channel_id', self.routes)


class TheChannelListIsWhereAChannelIsConnectedTests(unittest.TestCase):
    """Signing in belonged only to the publish dialog.

    That is the last place you look when setting a channel up, and the worst
    place to learn it is not connected - by then there is a finished video in
    hand. A channel is configured in the channel list, so that is where its
    account is connected and where it says where it actually posts.
    """

    def setUp(self) -> None:
        self.page = studio_ui()

    def test_each_channel_card_reports_its_account(self) -> None:
        self.assertIn("function channelAccountRow(channel)", self.page)
        self.assertIn("CHƯA ĐĂNG NHẬP", self.page)

    def test_a_channel_can_be_signed_in_from_its_card(self) -> None:
        self.assertIn("connectManagedChannel(", self.page)
        self.assertIn("/oauth/youtube/authorize?managed_channel_id=${channelId}", self.page)

    def test_the_card_can_confirm_which_youtube_channel_it_reaches(self) -> None:
        """One Google account can own several; the consent screen asks which."""
        self.assertIn("checkManagedChannelAccount(", self.page)
        self.assertIn("/api/oauth/youtube/channels?managed_channel_id=${channelId}", self.page)

    def test_borrowing_the_shared_account_is_shown_as_borrowing(self) -> None:
        self.assertIn("DÙNG CHUNG TÀI KHOẢN APP", self.page)

    def test_a_platform_with_no_uploader_says_so_instead(self) -> None:
        self.assertIn("chưa đăng tự động", self.page)

    def test_the_accounts_are_loaded_with_the_channels(self) -> None:
        """Written but never called is the defect this project keeps hitting."""
        self.assertIn("void loadManagedChannelAccounts();", self.page)


class AddingAChannelBySigningInTests(unittest.TestCase):
    """The account already knows which channel it granted.

    Adding a channel meant typing its name and URL into a form first, so a
    creator with ten channels filled ten forms from memory before finding out
    whether any of them connected. One consent grants one channel and YouTube
    will name it, so the order is reversed.
    """

    def setUp(self) -> None:
        self.routes = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "api" / "routes_oauth.py"
        ).read_text(encoding="utf-8")
        self.page = studio_ui()

    def test_a_sign_in_with_no_channel_adopts_the_one_it_granted(self) -> None:
        self.assertIn("if managed_channel_id is None:", self.routes)
        self.assertIn("def _adopt_signed_in_channel", self.routes)

    def test_the_row_is_built_from_what_youtube_reported(self) -> None:
        """Not from a name typed beforehand: this carries the real id."""
        self.assertIn("database.create_managed_channel(", self.routes)
        self.assertIn("youtube_channel_id=youtube_id", self.routes)

    def test_signing_in_again_updates_the_channel_rather_than_duplicating_it(self) -> None:
        """Recognition moved into a helper that also matches a pasted URL."""
        self.assertIn("existing = _find_existing_channel(youtube_id, handle)", self.routes)
        self.assertIn("def _find_existing_channel", self.routes)

    def test_the_token_is_moved_onto_the_channel_it_belongs_to(self) -> None:
        """Left app-wide, the next channel would silently share this account."""
        self.assertIn("shutil.move(str(oauth_token_path(None)), str(oauth_token_path(target_id)))", self.routes)

    def test_an_account_with_no_channel_is_reported_rather_than_crashing(self) -> None:
        self.assertIn("không có kênh YouTube nào", self.routes)

    def test_the_channel_panel_offers_it(self) -> None:
        self.assertIn("addChannelBySignIn()", self.page)
        self.assertIn("Thêm kênh bằng đăng nhập Google", self.page)

    def test_the_list_can_be_refreshed_after_the_google_tab(self) -> None:
        """The channel appears in another tab; this window has to be told."""
        self.assertIn("refreshManagedChannels()", self.page)


class RecognisingAChannelAddedBeforeSignInExistedTests(unittest.TestCase):
    """Rows typed in by hand carry a URL and no id.

    Matching on the id alone would make a second row for a channel the user
    already has, and leave the first one still borrowing the shared account.
    The id is usually sitting in the URL they pasted from YouTube.
    """

    def _find(self, channels, youtube_id, handle=""):
        import youtube_monitor.main  # import order: routes_oauth imports main
        from youtube_monitor.api import routes_oauth

        with mock.patch.object(routes_oauth.database, "list_managed_channels", return_value=channels):
            return routes_oauth._find_existing_channel(youtube_id, handle)

    def test_an_exact_id_wins(self) -> None:
        rows = [
            {"id": 1, "youtube_channel_id": "", "channel_url": "https://x/UC-other"},
            {"id": 2, "youtube_channel_id": "UC-me", "channel_url": ""},
        ]

        self.assertEqual(self._find(rows, "UC-me")["id"], 2)

    def test_an_id_inside_a_pasted_url_is_recognised(self) -> None:
        rows = [{
            "id": 7, "youtube_channel_id": "",
            "channel_url": "https://studio.youtube.com/channel/UCFqQ6k8CaYCArWvFFBsFaow",
        }]

        self.assertEqual(self._find(rows, "UCFqQ6k8CaYCArWvFFBsFaow")["id"], 7)

    def test_a_handle_in_the_url_is_recognised_too(self) -> None:
        rows = [{"id": 3, "youtube_channel_id": "", "channel_url": "https://www.youtube.com/@forestborn"}]

        self.assertEqual(self._find(rows, "UC-unknown", "@forestborn")["id"], 3)

    def test_an_unrelated_channel_is_not_claimed(self) -> None:
        """A wrong match would move a token onto somebody else's channel."""
        rows = [{"id": 1, "youtube_channel_id": "UC-a", "channel_url": "https://x/UC-a"}]

        self.assertIsNone(self._find(rows, "UC-b", "@b"))

    def test_the_missing_id_is_filled_in_when_it_is_recognised(self) -> None:
        routes = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "api" / "routes_oauth.py"
        ).read_text(encoding="utf-8")

        self.assertIn("database.update_managed_channel(target_id, youtube_channel_id=youtube_id)", routes)

    def test_the_module_can_reach_the_database_it_uses(self) -> None:
        """It called database.* without importing it, so it raised NameError
        at the moment a user finished signing in."""
        routes = (
            Path(__file__).resolve().parent.parent
            / "youtube_monitor" / "api" / "routes_oauth.py"
        ).read_text(encoding="utf-8")

        self.assertIn("from ..main import _api_error, database, publisher_worker", routes)
