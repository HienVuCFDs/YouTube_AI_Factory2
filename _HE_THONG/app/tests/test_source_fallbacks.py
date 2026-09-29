"""Nothing came back - carry on, and say so.

Extraction can come up empty for reasons that are nobody's mistake: a video
that is geo-blocked or deleted, an article page that will not open, a picture
that will not decode. Refusing there stopped the whole run on a source that
still had a title and a subject, which is exactly what an idea project has and
runs on perfectly well.

So the empty cases fall back to being analysed as an idea, with the reason
recorded, rather than raising. What must never happen is the opposite: quietly
producing a brief that reads as though the source had been examined.
"""

from __future__ import annotations

import unittest
from unittest import mock

from youtube_monitor import main as main_module
from youtube_monitor import source_brief


class WhenTheVideoCannotBeReachedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        video = {
            "youtube_video_id": "web-unreachable",
            "title": "Vì sao bầu trời chuyển đỏ",
            "description": "Giải thích tán xạ ánh sáng.",
            "duration_seconds": 180,
            "video_url": "https://gone.test/clip",
        }
        cls.video = video

    def _extract(self) -> source_brief.Extraction:
        project = {"youtube_video_id": "web-unreachable", "title": "Bầu trời đỏ"}
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-unreachable"), \
                mock.patch.object(main_module.database, "get_video", return_value=self.video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.database, "get_transcript", return_value=None), \
                mock.patch.object(
                    main_module, "_transcribe_video_source", side_effect=RuntimeError("404"),
                ), \
                mock.patch.object(main_module, "_source_contact_sheet", return_value=None):
            return main_module.extract_source(1, project, {})

    def test_a_dead_link_does_not_stop_the_run(self) -> None:
        extraction = self._extract()

        self.assertEqual(extraction.kind, "idea")
        self.assertFalse(extraction.has_visual_style)
        self.assertFalse(extraction.has_dialogue)

    def test_the_reason_is_carried_along_rather_than_discarded(self) -> None:
        notes = " ".join(self._extract().notes)

        self.assertIn("Không lấy được", notes)

    def test_the_brief_says_the_content_was_never_reached(self) -> None:
        """Proceeding is fine; proceeding while looking as though the source
        had been examined is not."""
        brief = source_brief.finalise({"limitations": []}, self._extract(), "codex_cli")

        joined = " ".join(brief["limitations"])
        self.assertIn("không có hình ảnh", joined.lower())
        self.assertFalse(brief["has_visual_style"])


class WhenThePageWillNotOpenTests(unittest.TestCase):
    def test_an_article_with_no_readable_body_keeps_its_title(self) -> None:
        video = {
            "youtube_video_id": "web-article",
            "title": "Lõi Trái Đất quay chậm lại",
            "description": "",
            "duration_seconds": 0,
            "video_url": "https://bao.test/x",
        }
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-article"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.web_research, "read_page", return_value=""):
            extraction = main_module.extract_source(1, {}, {"source_kind": "article"})

        self.assertEqual(extraction.kind, "idea")
        self.assertIn("Lõi Trái Đất", extraction.text)
        self.assertIn("Không đọc được nội dung", " ".join(extraction.notes))


class WhenThePicturesWillNotAssembleTests(unittest.TestCase):
    def test_the_file_names_are_used_rather_than_giving_up(self) -> None:
        assets = [
            {"asset_type": "image", "file_path": __file__, "original_name": "nui-lua.png"},
            {"asset_type": "image", "file_path": __file__, "original_name": "dai-duong.png"},
        ]
        with mock.patch.object(main_module, "_project_source_video_id", return_value=""), \
                mock.patch.object(main_module.database, "get_video", return_value={}), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=assets), \
                mock.patch.object(
                    main_module, "_contact_sheet_for_review", side_effect=RuntimeError("hỏng file"),
                ):
            extraction = main_module.extract_source(1, {}, {})

        self.assertEqual(extraction.kind, "idea")
        self.assertIn("nui-lua.png", extraction.text)
        self.assertIn("Không ghép được ảnh", " ".join(extraction.notes))

    def test_a_project_with_no_pictures_at_all_is_still_refused(self) -> None:
        """There is a difference between pictures that would not open and no
        pictures ever having been added."""
        from fastapi import HTTPException

        with mock.patch.object(main_module, "_project_source_video_id", return_value=""), \
                mock.patch.object(main_module.database, "get_video", return_value={}), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]):
            with self.assertRaises(HTTPException):
                main_module.extract_source(1, {}, {"source_kind": "images"})


if __name__ == "__main__":
    unittest.main()


class AListingIsReadAsAListingTests(unittest.TestCase):
    """The numbers on a shop page are claims about something a viewer may buy,
    so they are held to a different standard than a plot detail. None of the
    three marketplaces hands over a price to an automated fetch, which makes
    the price the field most likely to be invented."""

    PRODUCT = {
        "name": "Nước hoa EDT X-Men 49ml", "brand": "X-men", "category": "Nước hoa",
        "sku": "204631671", "price": "", "currency": "", "availability": "InStock",
        "images": [], "url": "https://www.lazada.vn/products/x.html",
        "route": "http_jsonld", "captured_at": "2026-09-27T00:00:00Z", "page_text": "",
    }

    def _extract(self, options: dict) -> object:
        video = {
            "youtube_video_id": "web-shop", "title": "Nước hoa",
            "description": "", "duration_seconds": 0,
            "video_url": "https://www.lazada.vn/products/x.html",
        }
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.page_source, "read_product", return_value=dict(self.PRODUCT)), \
                mock.patch.object(main_module, "ask_orchestrator_to_read", return_value="agt_test"), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            return main_module.extract_source(1, {}, options)

    def test_a_shop_link_is_detected_without_being_told(self) -> None:
        self.assertEqual(self._extract({}).kind, "product")

    def test_a_price_nobody_could_read_becomes_a_warning(self) -> None:
        warnings = " ".join(self._extract({}).warnings)

        self.assertIn("Không đọc được giá", warnings)
        self.assertIn("không được nêu bất kỳ con số giá nào", warnings)

    def test_a_price_typed_in_by_hand_wins(self) -> None:
        """The person looking at the page can read what an automated fetch
        cannot, and their figure is worth more than a blank."""
        extraction = self._extract({"price": "285000", "currency": "VND"})

        self.assertEqual(extraction.facts["price"], "285000")
        self.assertEqual(extraction.warnings, [])

    def test_what_was_read_off_the_page_is_kept_apart_from_what_a_model_says(self) -> None:
        facts = self._extract({}).facts

        self.assertEqual(facts["sku"], "204631671")
        self.assertEqual(facts["captured_at"], "2026-09-27T00:00:00Z")
        self.assertEqual(facts["route"], "http_jsonld")

    def test_a_shop_page_that_will_not_open_does_not_stop_the_run(self) -> None:
        video = {
            "youtube_video_id": "web-shop", "title": "Nước hoa X-Men",
            "description": "", "duration_seconds": 0,
            "video_url": "https://shopee.vn/x-i.1.2",
        }
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(
                    main_module.page_source, "read_product",
                    side_effect=main_module.page_source.PageSourceError("captcha"),
                ):
            extraction = main_module.extract_source(1, {}, {})

        self.assertEqual(extraction.kind, "idea")
        self.assertIn("X-Men", extraction.text)


class BringingInALinkThatIsNotAVideoTests(unittest.TestCase):
    """yt-dlp is asked first because a link is usually a video. When it is not,
    refusing meant a shop page or an article could not enter the app at all -
    while the analysis step already knew how to read both."""

    WALL = "<html><head><title>Security Check</title></head><body>Verify to continue</body></html>"
    REAL = (
        '<html><head><meta property="og:title" content="Điều khiển từ xa K-1028E" />'
        '<meta property="og:description" content="Điều khiển đa năng" /></head>'
        "<body>Cần đăng nhập</body></html>"
    )

    class _Sessions:
        def __init__(self, outcome: dict) -> None:
            self.outcome = outcome
            self.calls: list[str] = []

        def read(self, url: str, *, session_id: str = "") -> dict:
            self.calls.append(url)
            return dict(self.outcome)

    def test_a_readable_page_becomes_a_source(self) -> None:
        sessions = self._Sessions({"status": "OK"})
        with mock.patch.object(main_module.page_source, "fetch_static", return_value=self.REAL), \
                mock.patch.object(main_module.platform_connections, "manager", return_value=sessions):
            details = main_module._probe_page_link("https://shopee.vn/x-i.1.2")

        # A usable title on the static page means no browser is needed.
        self.assertEqual(sessions.calls, [])
        self.assertEqual(details["title"], "Điều khiển từ xa K-1028E")
        self.assertEqual(details["duration_seconds"], 0)
        self.assertEqual(details["platform"], "shop")

    def test_a_challenge_is_never_imported_as_a_source(self) -> None:
        sessions = self._Sessions({"status": "NEED_HUMAN_VERIFY", "probe": {}, "attempts": []})
        with mock.patch.object(main_module.page_source, "fetch_static", return_value=self.WALL), \
                mock.patch.object(main_module.platform_connections, "manager", return_value=sessions):
            self.assertIsNone(main_module._probe_page_link("https://shop.tiktok.com/vn/pdp/1"))
        self.assertEqual(sessions.calls, ["https://shop.tiktok.com/vn/pdp/1"])

    def test_a_marketplace_is_never_read_with_a_throwaway_browser(self) -> None:
        sessions = self._Sessions({"status": "NEED_LOGIN", "probe": {}, "attempts": []})
        with mock.patch.object(main_module.page_source, "fetch_static", return_value=self.WALL), \
                mock.patch.object(main_module.platform_connections, "manager", return_value=sessions), \
                mock.patch.object(main_module.page_source, "fetch_rendered") as throwaway:
            main_module._probe_page_link("https://shopee.vn/Tai-Nghe-S10-i.1.2")

        throwaway.assert_not_called()

    def test_a_page_a_session_was_served_is_named_after_the_product(self) -> None:
        """Read through a signed-in session, the listing names itself."""
        shell = "<html><head></head><body>Please enable JavaScript</body></html>"
        probe = {"url": "https://shopee.vn/x-i.1.2", "title": "Shopee",
                 "meta": {"og:title": "Điều khiển từ xa K-1028E"}, "ld": [], "prices": [], "images": []}
        sessions = self._Sessions({"status": "OK", "session": "extension:browser", "probe": probe})
        with mock.patch.object(main_module.page_source, "fetch_static", return_value=shell), \
                mock.patch.object(main_module.platform_connections, "manager", return_value=sessions):
            details = main_module._probe_page_link("https://shopee.vn/x-i.1.2")

        self.assertEqual(details["title"], "Điều khiển từ xa K-1028E")

    def test_a_blocked_shop_link_is_refused_in_words_the_user_can_act_on(self) -> None:
        """yt-dlp's "Unsupported URL" says nothing useful about a shop link,
        which was never going to be a video."""
        from fastapi import HTTPException

        with mock.patch.object(
                main_module, "probe_source_link",
                side_effect=main_module.SourceLinkError("Unsupported URL"),
        ), mock.patch.object(main_module, "_probe_page_link", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                main_module._import_video_from_link("https://shopee.vn/x-i.1.2")

        self.assertIn("chặn mọi cách đọc tự động", raised.exception.detail)
        self.assertNotIn("Unsupported URL", raised.exception.detail)


class TheRefusalNamesTheFixTests(unittest.TestCase):
    """Telling someone to "try again later" when the fix is one command away
    is the message failing at its only job."""

    def _refuse(self, has_profile: bool) -> str:
        from fastapi import HTTPException

        with mock.patch.object(
                main_module, "probe_source_link",
                side_effect=main_module.SourceLinkError("Unsupported URL"),
        ), mock.patch.object(main_module, "_probe_page_link", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                main_module._import_video_from_link("https://shopee.vn/x-i.1.2")
        return raised.exception.detail

    def test_it_says_the_one_thing_that_helps(self) -> None:
        """Nothing reads these pages - not an HTTP client, not a headless
        browser, not the CLI's own web reader. Telling someone to sign in does
        not help either: viewing a listing never required an account."""
        detail = self._refuse(has_profile=False)

        self.assertIn("shopee.vn", detail)
        self.assertIn("dán", detail)
        self.assertNotIn("đăng nhập", detail)

    def test_it_promises_not_to_invent_the_numbers(self) -> None:
        detail = self._refuse(has_profile=False)

        self.assertIn("không tự nghĩ ra con số nào", detail)

    def test_a_link_that_is_not_a_shop_keeps_the_original_reason(self) -> None:
        from fastapi import HTTPException

        with mock.patch.object(
                main_module, "probe_source_link",
                side_effect=main_module.SourceLinkError("Không đọc được video từ link"),
        ), mock.patch.object(main_module, "_probe_page_link", return_value=None):
            with self.assertRaises(HTTPException) as raised:
                main_module._import_video_from_link("https://example.test/abc")

        self.assertIn("Không đọc được video", raised.exception.detail)
        self.assertNotIn("shop_login", raised.exception.detail)


class HandingThePageToWhoeverCanOpenItTests(unittest.TestCase):
    """Every reader the app drives itself is refused by Shopee and TikTok
    Shop. The orchestrator is not: asked in its own window it returned the
    listing's name, its price, the shop and its rating. So a page the app
    cannot read is work for the one party that can, handed over through the
    queue it already pulls from."""

    def _extract(self, product: dict) -> object:
        video = {
            "youtube_video_id": "web-shop", "title": "Tai nghe",
            "description": "", "duration_seconds": 0,
            "video_url": "https://shopee.vn/Tai-Nghe-S10-i.1.2",
        }
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.page_source, "read_product", return_value=product), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            return main_module.extract_source(1, {}, {})

    def test_an_unreadable_listing_is_queued_for_the_orchestrator(self) -> None:
        unread = {"name": "Tai Nghe S10", "price": "", "images": [], "route": "url_slug",
                  "url": "https://shopee.vn/Tai-Nghe-S10-i.1.2", "captured_at": "2026-09-28T00:00:00Z"}

        with mock.patch.object(main_module, "ask_orchestrator_to_read", return_value="agt_x") as asked:
            warnings = " ".join(self._extract(unread).warnings)

        asked.assert_called_once()
        self.assertIn("Đã giao cho AI điều phối", warnings)
        self.assertIn("agt_x", warnings)

    def test_a_listing_that_was_read_is_not_queued(self) -> None:
        read = {"name": "Nước hoa", "price": "280.000", "currency": "₫", "images": ["https://a/1.jpg"],
                "route": "http_jsonld", "url": "https://www.lazada.vn/x.html", "captured_at": "x"}

        with mock.patch.object(main_module, "ask_orchestrator_to_read") as asked:
            extraction = self._extract(read)

        asked.assert_not_called()
        self.assertEqual(extraction.warnings, [])

    def test_the_same_link_is_not_queued_twice(self) -> None:
        """Re-running the step must not pile up duplicates of a job nobody
        has done yet."""
        waiting = [{
            "id": "agt_first", "status": "queued",
            "task_type": main_module.ORCHESTRATOR_READ_TASK,
            "input": {"url": "https://shopee.vn/Tai-Nghe-S10-i.1.2"},
        }]
        with mock.patch.object(main_module.database, "list_agent_tasks", return_value=waiting), \
                mock.patch.object(main_module.database, "create_agent_task") as created:
            task_id = main_module.ask_orchestrator_to_read(
                1, "https://shopee.vn/Tai-Nghe-S10-i.1.2", ["price"],
            )

        created.assert_not_called()
        self.assertEqual(task_id, "agt_first")

    def test_a_different_link_gets_its_own_task(self) -> None:
        waiting = [{
            "id": "agt_first", "status": "queued",
            "task_type": main_module.ORCHESTRATOR_READ_TASK,
            "input": {"url": "https://shopee.vn/khac-i.9.9"},
        }]
        with mock.patch.object(main_module.database, "list_agent_tasks", return_value=waiting), \
                mock.patch.object(
                    main_module.database, "create_agent_task", return_value={"id": "agt_second"},
                ) as created:
            task_id = main_module.ask_orchestrator_to_read(
                1, "https://shopee.vn/Tai-Nghe-S10-i.1.2", ["price"],
            )

        created.assert_called_once()
        self.assertEqual(task_id, "agt_second")


class WhoTheUnreadablePageGoesToTests(unittest.TestCase):
    """Assigning it to `astra` handed the page straight back to the CLI that
    had already failed to read it, and the task died with "astra: unavailable
    | claude: unavailable | antigravity: unavailable". What can open a
    marketplace is the desktop app, and the desktop app pulls its own work."""

    def test_it_never_goes_to_a_runtime_the_app_runs_itself(self) -> None:
        with mock.patch.object(main_module.database, "list_agent_tasks", return_value=[]), \
                mock.patch.object(
                    main_module.database, "create_agent_task", return_value={"id": "agt_x"},
                ) as created:
            main_module.ask_orchestrator_to_read(1, "https://shopee.vn/x-i.1.2", ["price"])

        assigned = created.call_args.kwargs["assigned_agent"]
        self.assertIn(assigned, {"chatgpt_app", "claude_chat"})
        self.assertNotIn(assigned, {"astra", "claude", "antigravity"})

    def test_a_connected_assistant_is_preferred(self) -> None:
        with mock.patch.object(
            main_module.chat_agent_presence, "connected", side_effect=lambda a: a == "claude_chat",
        ):
            self.assertEqual(main_module._reading_chat_agent(), "claude_chat")

    def test_with_nobody_attached_it_still_queues_for_the_proven_reader(self) -> None:
        """The work should be waiting when the app is next opened."""
        with mock.patch.object(main_module.chat_agent_presence, "connected", return_value=False):
            self.assertEqual(main_module._reading_chat_agent(), "chatgpt_app")
