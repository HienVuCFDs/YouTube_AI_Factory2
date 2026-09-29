"""The Connection Manager, the Browser Bridge and Step 1 around them.

No test here opens a browser: the profile reader and the sign-in check are
replaced with functions that return what real pages returned when measured
(a Shopee redirect to /verify/traffic/error, a TikTok page served under its
named URL, a Lazada price that exists only on screen, the header a signed-out
visitor sees).
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from youtube_monitor import ai_desktop_mcp, main as main_module, platform_connections as pc, source_brief
from youtube_monitor.tool_layer.registry import astra_tool_names

SHOPEE = "https://shopee.vn/Tai-Nghe-S10-i.196261835.29134843988"
TIKTOK = "https://shop.tiktok.com/vn/pdp/1733450240927368413"
LAZADA = "https://www.lazada.vn/products/pdp-i204631671-s254952397.html"

LISTING = {"url": SHOPEE, "title": "Tai Nghe S10 | Shopee Việt Nam", "text": "Tai Nghe S10 ₫159.000",
           "ld": [], "meta": {}, "prices": [{"text": "₫159.000", "size": 30, "top": 400, "struck": False}]}
SENT_AWAY = {"url": "https://shopee.vn/verify/traffic/error", "title": "Shopee", "text": "Cần đăng nhập",
             "ld": [], "meta": {}, "prices": []}
HOME_SIGNED_OUT = {"url": "https://shopee.vn/", "title": "Shopee", "text": (
    "bỏ qua nội dung chính Kênh Người Bán Trở thành Người bán Shopee Tải ứng dụng Kết nối Hỗ Trợ "
    "Tiếng Việt Đăng Ký Đăng Nhập Áo Khoác Hoodie Zip Dày Dặn DTH Giá Rẻ iPhone Áo Kiểu")}
HOME_SIGNED_IN = {"url": "https://shopee.vn/", "title": "Shopee", "text": (
    "bỏ qua nội dung chính Kênh Người Bán Trở thành Người bán Shopee Tải ứng dụng Kết nối Thông Báo "
    "Hỗ Trợ Tiếng Việt nguoidung_test Áo Khoác Hoodie Zip Dày Dặn DTH Giá Rẻ iPhone Áo Kiểu Bình Nước")}


class _Bridge(pc.BrowserBridge):
    """Cốc Cốc with the extension, answering every read with `answer`."""

    def __init__(self, answer: dict | None = None, *, connected: bool = True, capable: bool = True) -> None:
        super().__init__()
        self.answer = answer or {"ok": True, "result": LISTING}
        self.reads: list[tuple[str, str]] = []
        self.opened: list[tuple[str, str]] = []
        if connected:
            self.register("c1", {"capabilities": ["page_read", "open_tab"] if capable else [], "version": "1.3.0",
                                 "browser": "Cốc Cốc", "sites": list(pc.SITES)})

    def read(self, url: str, *, target: str = "", **_: float) -> dict:
        self.reads.append((url, target))
        return {**self.answer, "bridge": "coccoc"}

    def open_tab(self, url: str, *, target: str = "") -> dict:
        self.opened.append((url, target))
        return {"ok": True, "bridge": "coccoc"}


CAPTCHA = {"url": "https://shopee.vn/verify/captcha?anti_bot_tracking_id=x", "title": "Shopee", "text": "Xác minh"}


def _manager(store: Path, *, profile=None, checker=None, bridge=None, exists=True):
    return pc.ConnectionManager(
        store=pc._Store(store),
        bridge=bridge or _Bridge(connected=False),
        profile_reader=profile or (lambda url, platform: (pc.OK, "", dict(LISTING, url=url))),
        profile_checker=checker or (lambda platform: (pc.OK, dict(HOME_SIGNED_IN, url=platform.home_url))),
        profile_exists=lambda platform: exists,
    )


class _Temp(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.store = Path(self.folder.name) / "connections.json"

    def tearDown(self) -> None:
        self.folder.cleanup()


class ThePlatformsTests(unittest.TestCase):
    def test_the_five_marketplaces_are_known_by_link_domain_and_key(self) -> None:
        self.assertEqual([item.key for item in pc.PLATFORMS], ["shopee", "tiktok", "lazada", "tiki", "sendo"])
        self.assertEqual(pc.platform_of(SHOPEE).key, "shopee")
        self.assertEqual(pc.platform_of("www.lazada.vn").key, "lazada")
        self.assertEqual(pc.platform_of("profile:tiktok").key, "tiktok")
        self.assertIsNone(pc.platform_of("https://mail.google.com/"))

    def test_each_platform_has_its_own_profile_named_after_it(self) -> None:
        shopee = pc.profile_dir(pc.BY_KEY["shopee"])
        self.assertEqual(shopee.name, "shopee")
        self.assertEqual(shopee.parent, pc.PROFILES_ROOT)
        self.assertNotEqual(shopee, pc.profile_dir(pc.BY_KEY["tiktok"]))

    def test_the_profile_is_opened_persistent_never_fresh(self) -> None:
        source = inspect.getsource(pc._launch)
        self.assertIn("launch_persistent_context", source)
        self.assertNotIn("new_context(", source)

    def test_an_earlier_profile_is_moved_rather_than_lost(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder) / "state" / "profile_shop_lazada_vn"
            (legacy / "Default").mkdir(parents=True)
            with mock.patch("youtube_monitor.web_video_sidecar.STATE_DIR", Path(folder) / "state"), \
                    mock.patch.object(pc, "PROFILES_ROOT", Path(folder) / "profiles"):
                moved = pc.profile_dir(pc.BY_KEY["lazada"])
                self.assertTrue((moved / "Default").is_dir())
                self.assertFalse(legacy.exists())


class TellingAListingFromAWallTests(unittest.TestCase):
    def test_the_listing_itself_is_ok(self) -> None:
        self.assertEqual(pc.classify(SHOPEE, LISTING)[0], pc.OK)

    def test_shopee_sending_a_visitor_to_verify_asking_for_a_sign_in_is_need_login(self) -> None:
        """Measured 29/09: /verify/traffic/error, "Cần đăng nhập"."""
        self.assertEqual(pc.classify(SHOPEE, SENT_AWAY)[0], pc.NEED_LOGIN)

    def test_a_captcha_is_for_a_person_not_for_the_app(self) -> None:
        probe = {"url": TIKTOK, "title": "Security Check", "text": "Drag the puzzle piece into place"}
        self.assertEqual(pc.classify(TIKTOK, probe)[0], pc.NEED_HUMAN_VERIFY)

    def test_shopees_signed_out_cart_is_a_sign_in_wall(self) -> None:
        """Measured in Cốc Cốc 29/09: the listing rendered with its price as a
        grey block and "please log in to view cart" in the header."""
        probe = {"url": SHOPEE, "title": "Shopee Việt Nam | Mua và Bán", "text": "shopping cart please log in to view cart"}
        self.assertEqual(pc.classify(SHOPEE, probe)[0], pc.NEED_LOGIN)

    def test_tiktok_serving_the_listing_under_its_named_url_is_ok(self) -> None:
        probe = {"url": "https://shop.tiktok.com/vn/pdp/ban-chai-cha-giay/1733450240927368413?source=pd",
                 "title": "Bàn Chải Chà Giầy Dép Đa Năng", "text": "4.7 1095 đánh giá ₫25.000"}
        self.assertEqual(pc.classify(TIKTOK, probe)[0], pc.OK)


class TellingSignedInFromSignedOutTests(unittest.TestCase):
    shopee = pc.BY_KEY["shopee"]

    def test_a_header_offering_to_sign_in_is_signed_out(self) -> None:
        self.assertFalse(pc.signed_in(self.shopee, HOME_SIGNED_OUT)[0])

    def test_a_header_with_the_persons_name_is_signed_in(self) -> None:
        self.assertTrue(pc.signed_in(self.shopee, HOME_SIGNED_IN)[0])

    def test_the_sign_in_page_itself_is_not_signed_in(self) -> None:
        page = dict(HOME_SIGNED_IN, url="https://shopee.vn/buyer/login?next=x")
        self.assertFalse(pc.signed_in(self.shopee, page)[0])

    def test_a_page_still_loading_is_not_taken_as_signed_in(self) -> None:
        self.assertFalse(pc.signed_in(self.shopee, {"url": "https://shopee.vn/", "text": "Shopee"})[0])

    def test_another_site_is_not_this_platform(self) -> None:
        page = dict(HOME_SIGNED_IN, url="https://www.tiktok.com/foryou")
        self.assertFalse(pc.signed_in(pc.BY_KEY["tiktok"], page)[0])


class TheConnectionManagerTests(_Temp):
    def test_a_profile_platform_with_no_profile_is_disconnected(self) -> None:
        entry = _manager(self.store, exists=False).connection(pc.BY_KEY["lazada"])

        self.assertEqual(entry["status"], pc.DISCONNECTED)
        self.assertEqual(entry["mode"], "profile")
        self.assertIn("Kết nối Lazada", entry["next_action"])

    def test_checking_a_signed_in_profile_connects_it(self) -> None:
        entry = _manager(self.store).check("lazada")

        self.assertEqual(entry["status"], pc.CONNECTED)
        self.assertTrue(entry["connected_at"])

    def test_checking_a_signed_out_profile_asks_for_a_sign_in(self) -> None:
        signed_out = dict(HOME_SIGNED_OUT, url="https://www.lazada.vn/")
        entry = _manager(self.store, checker=lambda platform: (pc.OK, signed_out)).check("lazada")

        self.assertEqual(entry["status"], pc.STATUS_NEED_LOGIN)
        self.assertIn("đăng nhập", entry["detail"].lower())

    def test_a_connection_that_signs_out_has_expired(self) -> None:
        _manager(self.store).check("lazada")
        signed_out = dict(HOME_SIGNED_OUT, url="https://www.lazada.vn/")
        entry = _manager(self.store, checker=lambda platform: (pc.OK, signed_out)).check("lazada")

        self.assertEqual(entry["status"], pc.EXPIRED)
        self.assertIn("Đăng nhập lại", entry["next_action"])

    def test_a_captcha_on_the_check_needs_a_person(self) -> None:
        wall = {"url": "https://www.lazada.vn/", "title": "Security Check", "text": "Verify to continue"}
        entry = _manager(self.store, checker=lambda platform: (pc.OK, wall)).check("lazada")

        self.assertEqual(entry["status"], pc.STATUS_NEED_VERIFY)
        self.assertIn("tự xác minh", entry["detail"])

    def test_the_connection_outlives_the_app(self) -> None:
        _manager(self.store).check("lazada")
        self.assertEqual(_manager(self.store).connection(pc.BY_KEY["lazada"])["status"], pc.CONNECTED)

    def test_connecting_a_profile_platform_opens_its_window(self) -> None:
        manager = _manager(self.store)
        with mock.patch.object(pc.ConnectionManager, "_login_window") as window:
            answer = manager.connect("tiki")
        pc._profile_lock(pc.BY_KEY["tiki"]).release()

        self.assertEqual(answer["action"], "opened")
        window.assert_called_once()

    def test_a_second_connect_while_the_window_is_open_does_not_open_another(self) -> None:
        manager = _manager(self.store)
        lock = pc._profile_lock(pc.BY_KEY["sendo"])
        lock.acquire()
        try:
            self.assertEqual(manager.connect("sendo")["action"], "already_open")
        finally:
            lock.release()

    def test_disconnecting_removes_only_that_platforms_profile(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key in ("tiktok", "lazada"):
                (root / key / "Default").mkdir(parents=True)
            with mock.patch.object(pc, "PROFILES_ROOT", root):
                manager = pc.ConnectionManager(store=pc._Store(self.store), bridge=_Bridge(connected=False))
                entry = manager.disconnect("tiktok")

            self.assertEqual(entry["status"], pc.DISCONNECTED)
            self.assertFalse((root / "tiktok").exists())
            self.assertTrue((root / "lazada" / "Default").is_dir())

    def test_an_unknown_platform_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _manager(self.store).connect("amazon")


class ShopeeThroughThePersonsBrowserTests(_Temp):
    """Measured 29/09: Shopee sends any automated browser to /verify/captcha,
    signed in or not. So Shopee is connected through the person's own browser
    and the app launches nothing for it."""

    def test_connecting_shopee_launches_no_browser_and_offers_the_browsers_found(self) -> None:
        bridge = _Bridge()
        with mock.patch.object(pc.ConnectionManager, "_login_window") as window, \
                mock.patch.object(pc, "_launch") as launch:
            answer = _manager(self.store, bridge=bridge).connect("shopee")

        window.assert_not_called()
        launch.assert_not_called()
        self.assertEqual(answer["action"], "choose_bridge")
        self.assertEqual([row["id"] for row in answer["bridges"]], ["extension:coccoc"])
        self.assertEqual(answer["bridges"][0]["browser"], "Cốc Cốc")

    def test_with_no_browser_found_it_says_what_to_open(self) -> None:
        answer = _manager(self.store).connect("shopee")

        self.assertEqual(answer["bridges"], [])
        self.assertIn("Cốc Cốc", answer["message"])

    def test_the_sign_in_page_opens_as_a_tab_of_the_chosen_browser(self) -> None:
        bridge = _Bridge()
        answer = _manager(self.store, bridge=bridge).open_in_browser("shopee", "coccoc")

        self.assertEqual(bridge.opened, [("https://shopee.vn/buyer/login", "coccoc")])
        self.assertEqual(answer["via"], "extension:coccoc")

    def test_checking_reads_the_home_page_in_that_browser(self) -> None:
        bridge = _Bridge({"ok": True, "result": HOME_SIGNED_IN})
        entry = _manager(self.store, bridge=bridge).check("shopee", "coccoc")

        self.assertEqual(bridge.reads, [("https://shopee.vn/", "coccoc")])
        self.assertEqual(entry["status"], pc.CONNECTED)
        self.assertEqual(entry["summary"], "shopee: CONNECTED via extension:coccoc")

    def test_a_signed_out_browser_needs_a_sign_in_there(self) -> None:
        entry = _manager(self.store, bridge=_Bridge({"ok": True, "result": HOME_SIGNED_OUT})).check("shopee", "coccoc")

        self.assertEqual(entry["status"], pc.STATUS_NEED_LOGIN)
        self.assertIn("Cốc Cốc", entry["next_action"])

    def test_a_captcha_in_the_persons_browser_is_for_the_person(self) -> None:
        entry = _manager(self.store, bridge=_Bridge({"ok": True, "result": CAPTCHA})).check("shopee", "coccoc")

        self.assertEqual(entry["status"], pc.STATUS_NEED_VERIFY)
        self.assertIn("tự xác minh", entry["detail"])

    def test_reading_a_listing_in_that_browser_connects_it(self) -> None:
        manager = _manager(self.store, bridge=_Bridge())
        outcome = manager.read(SHOPEE)

        self.assertEqual(outcome["session"], "extension:coccoc")
        self.assertEqual(manager.connection(pc.BY_KEY["shopee"])["status"], pc.CONNECTED)

    def test_the_bridge_goes_before_the_app_profile(self) -> None:
        opened: list[str] = []

        def profile(url, platform):
            opened.append(url)
            return pc.OK, "", LISTING

        _manager(self.store, bridge=_Bridge(), profile=profile).read(SHOPEE)
        self.assertEqual(opened, [])

    def test_the_app_profile_is_a_fallback_tried_once_then_not_again_after_a_captcha(self) -> None:
        calls: list[str] = []

        def captcha(url, platform):
            calls.append(url)
            return pc.NEED_HUMAN_VERIFY, "captcha", CAPTCHA

        manager = _manager(self.store, profile=captcha)
        first = manager.read(SHOPEE)
        second = manager.read(SHOPEE)

        self.assertEqual(first["status"], pc.NEED_HUMAN_VERIFY)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second["attempts"][-1]["status"], pc.SKIPPED)

    def test_after_a_restart_the_remembered_browser_is_waited_for(self) -> None:
        """The extension reconnects within a minute of the app starting; a read
        made first must wait for it, not give up because nothing is there yet."""
        _manager(self.store, bridge=_Bridge({"ok": True, "result": HOME_SIGNED_IN})).check("shopee", "coccoc")
        asleep = _Bridge(connected=False)
        _manager(self.store, bridge=asleep).read(SHOPEE)

        self.assertEqual(asleep.reads, [(SHOPEE, "coccoc")])

    def test_disconnecting_shopee_signs_nobody_out(self) -> None:
        manager = _manager(self.store, bridge=_Bridge({"ok": True, "result": HOME_SIGNED_IN}), exists=False)
        manager.check("shopee", "coccoc")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(pc, "PROFILES_ROOT", Path(folder)):
            entry = manager.disconnect("shopee")

        self.assertEqual(entry["status"], pc.DISCONNECTED)
        self.assertEqual(entry["via"], "")


TIKTOK_B = "https://shop.tiktok.com/vn/pdp/1736013030170658013"
TIKTOK_HOME_SIGNED_OUT = {"url": "https://shop.tiktok.com/vn", "title": "TikTok Shop", "text": (
    "Bán hàng Thêm Tải ứng dụng Đăng nhập TikTok Shop Home Supplies Home Care Supplies Squeegees Bàn Chải Chà Giầy "
    "Dép Đa Năng Đồ gia dụng Chổi cao su Móc treo Khay cơm Tăm chỉ nha khoa")}
TIKTOK_LISTING = {
    "url": "https://shop.tiktok.com/vn/pdp/ban-chai-cha-giay-dep/1733450240927368413?source=product_detail",
    "title": "Bàn Chải Chà Giầy Dép Đa Năng - TikTok Shop Vietnam", "text": "Bàn Chải Chà Giầy Dép 4.7 1110 đánh giá",
    "ld": [], "images": [],
    "meta": {"og:title": "Bàn Chải Chà Giầy Dép Đa Năng",
             "og:url": "https://shop.tiktok.com/vn/pdp/ban-chai-cha-giay-dep/1733450240927368413?source=product_detail",
             "og:image": "https://p16-oec-sg.ibyteimg.com/x.webp"},
    "prices": [{"text": "₫ 9.999", "size": 36, "top": 91, "struck": True, "context": "-62% ₫ 9.999 26.000₫"},
               {"text": "₫ 9.999", "size": 36, "top": 95, "struck": False, "context": "₫ 9.999"},
               {"text": "26.000₫", "size": 17, "top": 112, "struck": True, "context": "-62% ₫ 9.999 26.000₫"}],
}
SECURITY_CHECK = {"url": "https://shop.tiktok.com/vn/pdp/1733450240927368413", "title": "Security Check",
                  "text": "Verify to continue: Drag the puzzle piece into place"}


class TikTokShopConnectionTests(_Temp):
    """Measured 29/09: headless answered "Security Check"; the person's own
    browser and the app's visible profile were both served the listing - at
    different prices (₫9.999 signed in, ₫11.546 signed out, same hour)."""

    def test_connecting_offers_the_persons_browser_and_the_apps_own_window(self) -> None:
        with mock.patch.object(pc.ConnectionManager, "_login_window") as window:
            answer = _manager(self.store, bridge=_Bridge()).connect("tiktok")

        window.assert_not_called()
        self.assertEqual(answer["action"], "choose_bridge")
        self.assertEqual([row["id"] for row in answer["bridges"]], ["extension:coccoc"])
        self.assertTrue(answer["profile_option"])

    def test_the_apps_own_window_opens_only_when_chosen(self) -> None:
        with mock.patch.object(pc.ConnectionManager, "_login_window") as window:
            answer = _manager(self.store).connect("tiktok", "profile")
        pc._profile_lock(pc.BY_KEY["tiktok"]).release()

        self.assertEqual(answer["action"], "opened")
        window.assert_called_once()

    def test_shopee_never_offers_the_apps_window(self) -> None:
        with mock.patch.object(pc.ConnectionManager, "_login_window") as window:
            answer = _manager(self.store, bridge=_Bridge()).connect("shopee", "profile")

        window.assert_not_called()
        self.assertEqual(answer["action"], "choose_bridge")
        self.assertFalse(answer["profile_option"])

    def test_a_browser_served_tiktok_is_connected_without_a_sign_in(self) -> None:
        entry = _manager(self.store, bridge=_Bridge({"ok": True, "result": TIKTOK_HOME_SIGNED_OUT})).check("tiktok", "coccoc")

        self.assertEqual(entry["status"], pc.CONNECTED)
        self.assertEqual(entry["summary"], "tiktok: CONNECTED via extension:coccoc")
        self.assertIn("không bắt buộc", entry["detail"])

    def test_a_security_check_needs_a_person(self) -> None:
        entry = _manager(self.store, bridge=_Bridge({"ok": True, "result": SECURITY_CHECK})).check("tiktok", "coccoc")

        self.assertEqual(entry["status"], pc.STATUS_NEED_VERIFY)
        self.assertFalse(entry["can_read"])
        self.assertIn("tự xác minh", entry["next_action"])

    def test_the_check_looks_at_a_listing_already_served(self) -> None:
        """Measured 29/09: TikTok's home page walled, a listing served, same
        browser, same minute."""
        bridge = _Bridge({"ok": True, "result": TIKTOK_LISTING})
        manager = _manager(self.store, bridge=bridge)
        manager.read(TIKTOK)
        manager.check("tiktok", "coccoc")

        self.assertEqual(bridge.reads[-1], (TIKTOK, "coccoc"))
        self.assertEqual(manager.connection(pc.BY_KEY["tiktok"])["status"], pc.CONNECTED)

    def test_shopee_is_still_checked_on_its_home_page(self) -> None:
        bridge = _Bridge({"ok": True, "result": HOME_SIGNED_IN})
        manager = _manager(self.store, bridge=bridge)
        manager.read(SHOPEE)
        manager.check("shopee", "coccoc")

        self.assertEqual(bridge.reads[-1], ("https://shopee.vn/", "coccoc"))

    def test_checking_the_apps_own_window(self) -> None:
        manager = _manager(self.store, checker=lambda platform: (pc.OK, TIKTOK_HOME_SIGNED_OUT))
        entry = manager.check("tiktok", "profile")

        self.assertEqual(entry["status"], pc.CONNECTED)
        self.assertEqual(entry["via"], "profile:tiktok")

    def test_the_connected_session_is_read_first(self) -> None:
        opened: list[str] = []
        manager = _manager(self.store, bridge=_Bridge({"ok": True, "result": TIKTOK_LISTING}),
                           profile=lambda url, platform: opened.append(url) or (pc.OK, "", TIKTOK_LISTING))
        manager.check("tiktok", "profile")
        outcome = manager.read(TIKTOK)

        self.assertEqual(outcome["session"], "profile:tiktok")
        self.assertEqual(len(opened), 1)

    def test_with_the_browser_gone_the_visible_profile_is_used(self) -> None:
        manager = _manager(self.store, profile=lambda url, platform: (pc.OK, "", TIKTOK_LISTING))
        outcome = manager.read(TIKTOK)

        self.assertEqual(outcome["session"], "profile:tiktok")
        self.assertEqual([item["status"] for item in outcome["attempts"]], [pc.UNAVAILABLE, pc.OK])
        self.assertEqual(manager.connection(pc.BY_KEY["tiktok"])["via"], "profile:tiktok")

    def test_the_bridge_is_asked_before_the_apps_profile(self) -> None:
        opened: list[str] = []
        bridge = _Bridge({"ok": True, "result": TIKTOK_LISTING})
        outcome = _manager(self.store, bridge=bridge,
                           profile=lambda url, platform: opened.append(url) or (pc.OK, "", TIKTOK_LISTING)).read(TIKTOK)

        self.assertEqual(outcome["session"], "extension:coccoc")
        self.assertEqual(opened, [])

    def test_a_security_check_everywhere_is_need_human_verify_and_tried_once(self) -> None:
        calls: list[str] = []

        def wall(url, platform):
            calls.append(url)
            return pc.NEED_HUMAN_VERIFY, "Security Check", SECURITY_CHECK

        manager = _manager(self.store, bridge=_Bridge({"ok": True, "result": SECURITY_CHECK}), profile=wall)
        first = manager.read(TIKTOK)
        manager.read(TIKTOK)

        self.assertEqual(first["status"], pc.NEED_HUMAN_VERIFY)
        self.assertIn("tự xác minh", first["detail"])
        self.assertEqual(len(calls), 1)

    def test_the_apps_profile_is_tried_again_after_the_cooldown(self) -> None:
        calls: list[str] = []
        manager = _manager(self.store, profile=lambda url, platform: calls.append(url) or
                           (pc.NEED_HUMAN_VERIFY, "Security Check", SECURITY_CHECK))
        manager.read(TIKTOK)
        earlier = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
        manager.store.put("tiktok|profile", at=earlier)
        manager.read(TIKTOK)

        self.assertEqual(len(calls), 2)

    def test_shopees_profile_is_not_retried_after_any_wait(self) -> None:
        calls: list[str] = []
        manager = _manager(self.store, profile=lambda url, platform: calls.append(url) or
                           (pc.NEED_HUMAN_VERIFY, "captcha", CAPTCHA))
        manager.read(SHOPEE)
        manager.store.put("shopee|profile", at="2020-01-01T00:00:00+00:00")
        manager.read(SHOPEE)

        self.assertEqual(len(calls), 1)

    def test_the_connection_outlives_the_app(self) -> None:
        _manager(self.store, bridge=_Bridge({"ok": True, "result": TIKTOK_HOME_SIGNED_OUT})).check("tiktok", "coccoc")
        asleep = _Bridge(connected=False)
        _manager(self.store, bridge=asleep).read(TIKTOK)

        self.assertEqual(asleep.reads, [(TIKTOK, "coccoc")])


class WhatATikTokReadKeepsTests(unittest.TestCase):
    def test_the_seller_and_standing_the_page_writes(self) -> None:
        """Measured 29/09: "... Do Shop Gia Dụng Tú Anh bán 4.7 (1.1K) 19.8K đã được bán"."""
        text = "Freeship Bàn Chải Chà Giầy Dép Do Shop Gia Dụng Tú Anh bán 4.7 (1.1K) 19.8K đã được bán Thông số"
        self.assertEqual(main_module.page_source.listing_facts_from_text(text), {
            "seller": "Shop Gia Dụng Tú Anh", "rating": "4.7", "review_count": "1.1K", "sold_count": "19.8K",
        })

    def test_no_seller_is_invented(self) -> None:
        self.assertEqual(main_module.page_source.listing_facts_from_text("Nước hoa 4.9 (1075) đánh giá"), {})

    def test_price_old_price_discount_id_and_canonical_address(self) -> None:
        class Served:
            def read(self, url, *, session_id=""):
                return {"status": "OK", "session": "extension:coccoc", "site": "shop.tiktok.com",
                        "probe": TIKTOK_LISTING, "attempts": []}

        with mock.patch.object(main_module.page_source, "fetch_static",
                               return_value="<html><head><title>Security Check</title></head></html>"):
            product = main_module.page_source.read_product(TIKTOK, sessions=Served())

        self.assertEqual(product["name"], "Bàn Chải Chà Giầy Dép Đa Năng")
        self.assertEqual((product["price"], product["price_text"]), ("9999", "₫ 9.999"))
        self.assertEqual((product["original_price"], product["discount"]), ("26000", "-62%"))
        self.assertEqual(product["product_id"], "1733450240927368413")
        self.assertEqual(product["canonical_url"],
                         "https://shop.tiktok.com/vn/pdp/ban-chai-cha-giay-dep/1733450240927368413")
        self.assertEqual(product["session"], "extension:coccoc")
        self.assertTrue(product["captured_at"])
        self.assertEqual(product["images"], ["https://p16-oec-sg.ibyteimg.com/x.webp"])

    def test_the_brief_keeps_them_as_facts(self) -> None:
        product = {"name": "Bàn chải", "price": "9999", "currency": "VND", "price_text": "₫ 9.999",
                   "original_price": "26000", "discount": "-62%", "product_id": "1733450240927368413",
                   "canonical_url": "https://shop.tiktok.com/vn/pdp/x/1733450240927368413", "images": ["https://i/1.webp"],
                   "read_status": "OK", "session": "extension:coccoc", "route": "session:extension:coccoc",
                   "captured_at": "2026-09-29T09:00:00+00:00"}
        video = {"youtube_video_id": "web-tt", "title": "Bàn chải", "description": "", "duration_seconds": 0,
                 "video_url": TIKTOK}
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-tt"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.page_source, "read_product", return_value=product), \
                mock.patch.object(main_module, "_withdraw_read_tasks", return_value=[]), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            facts = main_module.extract_source(1, {}, {}).facts

        for key in ("price", "original_price", "discount", "product_id", "canonical_url", "images", "session",
                    "captured_at"):
            self.assertIn(key, facts)


class ReadingThroughTheConnectionsTests(_Temp):
    def test_a_platform_that_needs_no_sign_in_is_read_through_its_own_profile(self) -> None:
        bridge = _Bridge()
        outcome = _manager(self.store, bridge=bridge, exists=False).read(LAZADA)

        self.assertEqual(outcome["session"], "profile:lazada")
        self.assertEqual(bridge.reads, [])

    def test_a_connected_profile_turned_away_has_expired(self) -> None:
        manager = _manager(self.store, profile=lambda url, platform: (pc.NEED_LOGIN, "cần đăng nhập", SENT_AWAY))
        manager.check("lazada")
        manager.read(LAZADA)

        self.assertEqual(manager.connection(pc.BY_KEY["lazada"])["status"], pc.EXPIRED)

    def test_nothing_left_for_shopee_names_the_persons_browser(self) -> None:
        manager = _manager(self.store, profile=lambda url, platform: (pc.NEED_HUMAN_VERIFY, "captcha", CAPTCHA))
        manager.read(SHOPEE)
        outcome = manager.read(SHOPEE)

        self.assertEqual(outcome["status"], pc.NEED_LOGIN)
        self.assertIn("trình duyệt có extension", outcome["detail"])
        self.assertIn("profile:shopee", [row["id"] for row in outcome["sessions"]])

    def test_the_persons_browser_is_asked_again_after_a_sign_in_wall(self) -> None:
        """They sign in to their own browser without telling the app."""
        bridge = _Bridge({"ok": True, "result": SENT_AWAY})
        manager = _manager(self.store, bridge=bridge, profile=lambda url, p: (pc.NEED_HUMAN_VERIFY, "c", CAPTCHA))
        manager.read(SHOPEE)
        bridge.answer = {"ok": True, "result": LISTING}

        self.assertEqual(manager.read(SHOPEE)["session"], "extension:coccoc")
        self.assertEqual(len(bridge.reads), 2)

    def test_a_named_session_is_the_only_one_used(self) -> None:
        bridge = _Bridge()
        outcome = _manager(self.store, bridge=bridge).read(LAZADA, session_id="extension:coccoc")

        self.assertEqual([item["session"] for item in outcome["attempts"]], ["extension:coccoc"])
        self.assertEqual(bridge.reads, [(LAZADA, "coccoc")])

    def test_one_platforms_profile_is_not_used_for_another(self) -> None:
        outcome = _manager(self.store).read(LAZADA, session_id="profile:shopee")
        self.assertEqual(outcome["status"], pc.UNAVAILABLE)

    def test_only_marketplaces_are_read(self) -> None:
        bridge = _Bridge()
        outcome = _manager(self.store, bridge=bridge).read("https://mail.google.com/mail/u/0/")

        self.assertEqual(outcome["status"], pc.UNAVAILABLE)
        self.assertEqual(bridge.reads, [])

    def test_a_captcha_url_is_need_human_verify_whatever_the_page_says(self) -> None:
        probe = dict(CAPTCHA, text="Cần đăng nhập")
        self.assertEqual(pc.classify(SHOPEE, probe)[0], pc.NEED_HUMAN_VERIFY)


class TheBrowserBridgeTests(unittest.TestCase):
    """No heartbeat: an idle extension sleeps, and a request waits for it."""

    def test_the_app_sends_no_heartbeat(self) -> None:
        source = inspect.getsource(main_module.browser_scene_jobs_ws)
        self.assertNotIn('"ping"', source)
        self.assertFalse(hasattr(main_module, "BROWSER_BRIDGE_PING_SECONDS"))

    def test_a_request_made_while_the_extension_sleeps_is_sent_when_it_wakes(self) -> None:
        bridge = pc.BrowserBridge()
        answer: dict = {}
        worker = threading.Thread(target=lambda: answer.update(bridge.read(SHOPEE, wake_seconds=5, work_seconds=5)))
        worker.start()
        time.sleep(0.2)
        # The extension reconnects (its own alarm woke it) and says hello.
        bridge.register("woke", {"capabilities": ["page_read"]})
        messages = bridge.outbox("woke")
        self.assertEqual([item["url"] for item in messages], [SHOPEE])
        bridge.resolve(messages[0]["request_id"], {"ok": True, "result": LISTING})
        worker.join(3)
        self.assertTrue(answer["ok"])

    def test_an_extension_that_does_not_wake_in_time_is_a_plain_failure(self) -> None:
        answer = pc.BrowserBridge().read(SHOPEE, wake_seconds=0.2, work_seconds=0.2)
        self.assertFalse(answer["ok"])
        self.assertIn("không thức dậy", answer["error"])

    def test_a_recently_seen_extension_is_on_standby_not_offline(self) -> None:
        bridge = pc.BrowserBridge()
        bridge.register("c1", {"capabilities": ["page_read"], "browser": "Cốc Cốc"})
        bridge.unregister("c1")
        state = bridge.state()

        self.assertEqual(state["status"], pc.BRIDGE_STANDBY)
        self.assertTrue(state["can_read"])

    def test_one_never_seen_is_offline(self) -> None:
        self.assertEqual(pc.BrowserBridge().state()["status"], pc.BRIDGE_OFFLINE)

    def test_an_old_extension_is_reported_as_needing_a_reload(self) -> None:
        bridge = pc.BrowserBridge()
        bridge.register("old")
        self.assertEqual(bridge.state()["status"], pc.BRIDGE_OUTDATED)
        self.assertEqual(bridge.outbox("old"), [])

    def test_a_disconnect_mid_read_ends_the_wait(self) -> None:
        bridge = pc.BrowserBridge()
        bridge.register("c1", {"capabilities": ["page_read"]})
        answer: dict = {}
        worker = threading.Thread(target=lambda: answer.update(bridge.read(SHOPEE, wake_seconds=5, work_seconds=5)))
        worker.start()
        while not bridge.outbox("c1"):
            time.sleep(0.01)
        bridge.unregister("c1")
        worker.join(2)
        self.assertFalse(answer["ok"])

    def test_a_read_goes_out_and_comes_back_over_the_socket(self) -> None:
        client = TestClient(main_module.app)
        answer: dict = {}
        with client.websocket_connect("/ws/browser-scene-jobs") as socket:
            socket.send_json({"type": "hello", "version": "1.2.0", "capabilities": ["page_read"],
                              "browser": "Cốc Cốc", "sites": list(pc.SITES)})
            reader = threading.Thread(target=lambda: answer.update(pc.BRIDGE.read(SHOPEE, wake_seconds=10)))
            reader.start()
            message = socket.receive_json()
            while message.get("type") != "page_read":
                message = socket.receive_json()
            socket.send_json({"type": "page_read_result", "request_id": message["request_id"], "ok": True,
                              "result": LISTING})
            reader.join(10)
        self.assertTrue(answer.get("ok"))
        self.assertEqual(answer["result"]["title"], LISTING["title"])

    def test_the_extension_reads_a_page_exactly_as_the_app_does(self) -> None:
        script = (Path(main_module.__file__).parents[1] / "browser_extension" / "background.js").read_text(encoding="utf-8")
        start = script.index("function probePage() {") + len("function probePage() {")
        extension_copy = script[start:script.index("function pageShowsAPrice")].rsplit("}", 1)[0]
        app_copy = pc.PROBE_JS[len("() => {"):].rsplit("}", 1)[0]
        squash = lambda text: re.sub(r"\s+", " ", text).strip()  # noqa: E731

        self.assertEqual(squash(extension_copy), squash(app_copy))


class NothingSecretReachesTheAiTests(_Temp):
    def test_the_module_never_reads_cookies(self) -> None:
        self.assertNotIn(".cookies(", inspect.getsource(pc))

    def test_the_extension_has_no_cookie_permission(self) -> None:
        manifest = json.loads(
            (Path(main_module.__file__).parents[1] / "browser_extension" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("cookies", manifest["permissions"])

    def test_the_ai_sees_capabilities_only(self) -> None:
        view = _manager(self.store, bridge=_Bridge()).capabilities()
        text = json.dumps(view, ensure_ascii=False).lower()

        self.assertEqual([row["platform"] for row in view["platforms"]], ["shopee", "tiktok", "lazada", "tiki", "sendo"])
        self.assertEqual(view["browser_bridges"][0]["id"], "extension:coccoc")
        for word in ("cookie", "password", "mật khẩu", "token", "appdata", "profiles", "checked_at"):
            self.assertNotIn(word, text)

    def test_a_read_handed_to_an_ai_is_the_page_trimmed(self) -> None:
        view = pc.public_view({"status": "OK", "session": "profile:shopee", "probe": dict(LISTING, text="x" * 9000),
                               "attempts": []})

        self.assertNotIn("probe", view)
        self.assertEqual(view["page"]["product"]["price"], "159000")
        self.assertEqual(len(view["page"]["text"]), 4000)


class TheConnectionEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main_module.app)

    def test_the_manager_lists_every_platform_and_the_bridge(self) -> None:
        data = self.client.get("/api/connections").json()
        self.assertEqual(len(data["platforms"]), 5)
        self.assertIn("status", data["browser_bridge"])

    def test_the_ai_view_is_the_capability_list(self) -> None:
        data = self.client.get("/api/connections?view=capabilities").json()
        self.assertIn("read_with", data)
        self.assertIn("summary", data["platforms"][0])
        self.assertNotIn("checked_at", json.dumps(data))

    def test_an_unknown_platform_is_a_404(self) -> None:
        self.assertEqual(self.client.post("/api/connections/amazon/connect").status_code, 404)

    def test_reading_a_page_that_is_no_marketplace_is_refused(self) -> None:
        response = self.client.post("/api/connections/read", json={"url": "https://mail.google.com/mail/u/0/"})
        self.assertEqual(response.status_code, 400)

    def test_the_panel_is_in_the_tools_and_connections_tab(self) -> None:
        from tests.ui_source import studio_markup, studio_ui

        self.assertIn('id="platformConnectionsPanel"', studio_markup())
        ui = studio_ui()
        self.assertIn("'platformConnectionsPanel'", ui)
        for action in ("Kết nối", "Kiểm tra", "Đăng nhập lại", "Ngắt kết nối"):
            self.assertIn(f">{action}</button>", ui)


def _extraction(kind: str = "article") -> source_brief.Extraction:
    return source_brief.Extraction(kind=kind, text="Nội dung", text_label="x", metadata={"title": "T"})


class StepOneAnalysisTests(unittest.TestCase):
    def _analyze(self, options: dict, report_runtime: str = "claude_code_cli") -> tuple[dict, dict]:
        seen: dict = {}

        def call(*args, **kwargs):
            seen.update(kwargs)
            kwargs["report"].update(runtime=report_runtime)
            return {"topic": "T", "content_summary": "S", "limitations": []}

        with mock.patch.object(main_module, "extract_source", return_value=_extraction()), \
                mock.patch.object(main_module, "_project_source_video_id", return_value="vid"), \
                mock.patch.object(main_module.database, "get_video", return_value={"title": "T"}), \
                mock.patch.object(main_module, "_call_orchestrator_json", side_effect=call), \
                mock.patch.object(main_module, "analysis_is_about_the_source", return_value=True), \
                mock.patch.object(main_module.database, "save_video_analysis") as saved:
            result = main_module._step_analyze(1, {"title": "T"}, options)
        return result, {"call": seen, "saved": saved.call_args_list}

    def test_the_runtime_that_answered_is_written_into_the_brief(self) -> None:
        result, trace = self._analyze({})

        self.assertEqual(result["result"]["provider"], "claude_code_cli")
        self.assertEqual(trace["saved"][0].kwargs["provider"], "claude_code_cli")

    def test_options_provider_reaches_the_call(self) -> None:
        _, trace = self._analyze({"provider": "Claude"})
        self.assertEqual(trace["call"]["provider"], "claude")

    def test_a_named_provider_is_the_only_one_tried(self) -> None:
        calls: list[str] = []
        with mock.patch.object(main_module, "call_codex_json", side_effect=lambda *a, **k: calls.append("codex")), \
                mock.patch.object(main_module, "call_claude_code_cli_json",
                                  side_effect=lambda *a, **k: calls.append("claude") or {"ok": 1}), \
                mock.patch.object(main_module.orchestrator_runtime, "runtime_readiness", return_value={}), \
                mock.patch.object(main_module.orchestrator_runtime, "gate",
                                  side_effect=lambda readiness, order: {"ready": list(order), "blocked": []}), \
                mock.patch.object(main_module, "_record_orchestrator_step"):
            report: dict = {}
            main_module._call_orchestrator_json("s", "u", {}, provider="claude", report=report)

        self.assertEqual(calls, ["claude"])
        self.assertEqual(report["runtime"], "claude_code_cli")

    def test_a_provider_that_cannot_look_at_pictures_is_refused_plainly(self) -> None:
        with self.assertRaises(main_module.ProviderNotSupported):
            main_module._call_orchestrator_json("s", "u", {}, provider="antigravity", image_path=Path(__file__))

    def test_the_refusal_reaches_the_caller_as_a_400(self) -> None:
        with mock.patch.object(main_module, "extract_source", return_value=_extraction()), \
                mock.patch.object(main_module, "_project_source_video_id", return_value="vid"), \
                mock.patch.object(main_module.database, "get_video", return_value={}), \
                mock.patch.object(main_module, "_call_orchestrator_json",
                                  side_effect=main_module.ProviderNotSupported("không làm được")):
            with self.assertRaises(HTTPException) as raised:
                main_module._step_analyze(1, {}, {"provider": "openai_gpt"})
        self.assertEqual(raised.exception.status_code, 400)

    def test_an_article_is_read_from_the_page_even_when_it_has_a_description(self) -> None:
        """Measured on vnexpress: 151 characters of description were analysed
        while the page held 9,083."""
        video = {"title": "Khoa học", "description": "Tin khoa học mới nhất.", "duration_seconds": 0,
                 "video_url": "https://vnexpress.net/khoa-hoc-cong-nghe"}
        body = "Bài viết dài về khoa học. " * 200
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-a"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.web_research, "read_page", return_value=body) as read_page, \
                mock.patch.object(main_module.page_source, "fetch_static", return_value=""), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            extraction = main_module.extract_source(1, {}, {"source_kind": "article"})

        read_page.assert_called_once()
        self.assertGreater(len(extraction.text), 1000)
        self.assertNotIn("Tin khoa học mới nhất", extraction.text)

    def test_the_description_is_the_fallback_when_the_page_will_not_open(self) -> None:
        video = {"title": "Khoa học", "description": "Tin khoa học mới nhất hôm nay.", "duration_seconds": 0,
                 "video_url": "https://vnexpress.net/khoa-hoc-cong-nghe"}
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-a"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.web_research, "read_page", return_value=""), \
                mock.patch.object(main_module.page_source, "fetch_static", return_value=""), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            extraction = main_module.extract_source(1, {}, {"source_kind": "article"})

        self.assertEqual(extraction.kind, "article")
        self.assertIn("mô tả ngắn", " ".join(extraction.notes))


class ChoosingTheConnectionForAnalysisTests(unittest.TestCase):
    VIDEO = {"youtube_video_id": "web-shop", "title": "Tai nghe", "description": "", "duration_seconds": 0,
             "video_url": SHOPEE}

    def _extract(self, product: dict, options: dict):
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video", return_value=self.VIDEO), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.page_source, "read_product", return_value=product) as reader, \
                mock.patch.object(main_module, "ask_orchestrator_to_read", return_value=""), \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            return main_module.extract_source(1, {}, options), reader

    def test_the_chosen_connection_is_handed_to_the_reader(self) -> None:
        product = {"name": "Tai nghe", "price": "159000", "read_status": "OK", "session": pc.EXTENSION_ID}
        extraction, reader = self._extract(product, {"browser_session": pc.EXTENSION_ID})

        self.assertEqual(reader.call_args.kwargs["session_id"], pc.EXTENSION_ID)
        self.assertEqual(extraction.facts["read_status"], "OK")

    def test_a_chosen_connection_that_fails_says_what_else_there_is(self) -> None:
        product = {"name": "Tai nghe", "price": "", "read_status": "NEED_LOGIN", "read_detail": "cần đăng nhập",
                   "sessions": [{"id": "profile:shopee", "status": "NEED_HUMAN_VERIFY"},
                                {"id": "extension:coccoc", "status": "connected"}]}
        with self.assertRaises(HTTPException) as raised:
            self._extract(product, {"browser_session": "profile:shopee"})

        self.assertEqual(raised.exception.status_code, 424)
        self.assertIn("NEED_LOGIN", raised.exception.detail)

    def test_without_a_choice_an_unread_listing_is_a_warning_not_a_stop(self) -> None:
        product = {"name": "Tai nghe", "price": "", "read_status": "NEED_LOGIN", "read_detail": "cần đăng nhập"}
        extraction, _ = self._extract(product, {})

        self.assertIn("NEED_LOGIN", " ".join(extraction.warnings))


class AnUnreadListingIsNotAFinishedAnalysisTests(unittest.TestCase):
    def _verify(self, facts: dict) -> dict:
        saved = {"result": {"source_type": "product", "source_facts": facts}}
        with mock.patch.object(main_module, "_steps_done", return_value={"analyze"}), \
                mock.patch.object(main_module.database, "get_production_project", return_value={"id": 1}), \
                mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video_analysis", return_value=saved), \
                mock.patch.object(main_module.database, "get_latest_project_script", return_value=None):
            return main_module._verify_goal(1, ["analyze"])

    def test_a_brief_from_the_url_alone_does_not_pass(self) -> None:
        check = self._verify({"read_status": "NEED_LOGIN"})

        self.assertFalse(check["passed"])
        self.assertIn("youtube_factory_list_connections", check["reasons"]["analyze"])

    def test_a_brief_from_the_listing_passes(self) -> None:
        self.assertTrue(self._verify({"read_status": "OK", "price": "159000"})["passed"])


class TheOrchestratorSeesCapabilitiesTests(unittest.TestCase):
    def test_the_three_tools_are_offered(self) -> None:
        for name in ("youtube_factory_list_connections", "youtube_factory_get_connection_status",
                     "youtube_factory_read_product"):
            self.assertIn(name, astra_tool_names())

    def test_they_go_to_the_connection_endpoints(self) -> None:
        paths: list[str] = []
        with mock.patch.object(ai_desktop_mcp, "_factory_request",
                               side_effect=lambda path, **kw: paths.append(path) or {}):
            ai_desktop_mcp._call_tool("youtube_factory_list_connections", {})
            ai_desktop_mcp._call_tool("youtube_factory_get_connection_status", {"platform": "shopee"})
            ai_desktop_mcp._call_tool("youtube_factory_read_product", {"url": SHOPEE})

        self.assertEqual(paths, ["/api/connections?view=capabilities", "/api/connections/shopee",
                                 "/api/connections/read"])

    def test_the_agent_is_told_how_to_recover_an_unread_listing(self) -> None:
        from youtube_monitor import agent_loop

        self.assertIn("youtube_factory_list_connections", agent_loop.INSTRUCTIONS)
        self.assertIn("Không tự giải captcha", agent_loop.INSTRUCTIONS)


class AListingTheAppHasReadNeedsNoOneElseTests(unittest.TestCase):
    def test_an_open_request_to_read_it_is_withdrawn(self) -> None:
        """Measured 29/09: agt_78846175 stayed queued for GPT Work after the
        app had read the same listing through Cốc Cốc."""
        waiting = [{"id": "agt_old", "status": "queued", "task_type": main_module.ORCHESTRATOR_READ_TASK,
                    "input": {"url": SHOPEE}}]
        product = {"name": "Tai nghe", "price": "119000.00", "currency": "VND", "read_status": "OK",
                   "route": "session:extension:coccoc", "session": "extension:coccoc"}
        video = {"youtube_video_id": "web-shop", "title": "Tai nghe", "description": "", "duration_seconds": 0,
                 "video_url": SHOPEE}
        with mock.patch.object(main_module, "_project_source_video_id", return_value="web-shop"), \
                mock.patch.object(main_module.database, "get_video", return_value=video), \
                mock.patch.object(main_module.database, "list_project_assets", return_value=[]), \
                mock.patch.object(main_module.page_source, "read_product", return_value=product), \
                mock.patch.object(main_module.database, "list_agent_tasks", return_value=waiting), \
                mock.patch.object(main_module.database, "finish_agent_task") as finished, \
                mock.patch.object(main_module, "_sheet_from_remote_images", return_value=(None, 0)):
            main_module.extract_source(1, {}, {})

        finished.assert_called()
        self.assertEqual(finished.call_args.args[:2], ("agt_old", "cancelled"))

    def test_a_listing_still_unread_keeps_its_request(self) -> None:
        with mock.patch.object(main_module.database, "list_agent_tasks", return_value=[]), \
                mock.patch.object(main_module.database, "finish_agent_task") as finished:
            main_module._withdraw_read_tasks(SHOPEE, "x")
        finished.assert_not_called()


class TheSameListingIsQueuedOnceTests(unittest.TestCase):
    def test_a_tracking_query_does_not_make_a_second_task(self) -> None:
        waiting = [{"id": "agt_first", "status": "queued", "task_type": main_module.ORCHESTRATOR_READ_TASK,
                    "input": {"url": SHOPEE + "?sp_atk=abc"}}]
        with mock.patch.object(main_module.database, "list_agent_tasks", return_value=waiting) as listed, \
                mock.patch.object(main_module.database, "create_agent_task") as created:
            task_id = main_module.ask_orchestrator_to_read(1, SHOPEE, ["price"])

        created.assert_not_called()
        self.assertEqual(task_id, "agt_first")
        self.assertEqual({call.kwargs.get("status") for call in listed.call_args_list}, {"queued", "running"})


if __name__ == "__main__":
    unittest.main()
