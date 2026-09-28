"""Reading a page that is for sale, or for reading.

Measured against the three Vietnamese marketplaces the user sells from, which
fail in three different ways: Lazada publishes a JSON-LD `Product` over plain
HTTP, TikTok Shop needs a browser and sometimes answers with a captcha, and
Shopee renders "Cần đăng nhập" with no product block, no pictures and no
price.

Not one of the three hands over a price to an automated fetch - Lazada's own
`offers` block has no price field at all. So the thing these tests guard hardest
is that a missing price is reported as missing, loudly, rather than left as an
empty string for a writer to fill in from nowhere.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from youtube_monitor import page_source


def _page(blocks: list[dict] | None = None, metas: dict[str, str] | None = None) -> str:
    parts = ["<html><head>"]
    for block in blocks or []:
        parts.append(
            f'<script type="application/ld+json">{json.dumps(block, ensure_ascii=False)}</script>'
        )
    for key, value in (metas or {}).items():
        parts.append(f'<meta property="{key}" content="{value}" />')
    parts.append("</head><body><p>Nội dung</p></body></html>")
    return "".join(parts)


LAZADA_LIKE = {
    "@type": "Product",
    "name": "Nước hoa EDT X-Men for Boss Intense 49ml",
    "image": ["//cdn.test/a.jpg", "https://cdn.test/b.jpg"],
    "brand": {"@type": "Brand", "name": "X-men for Boss"},
    "category": "Làm đẹp > Nước hoa",
    "sku": "204631671",
    "description": "Hương trầm, lưu hương 48h.",
    # Exactly as Lazada publishes it: an Offer with no price in it.
    "offers": {"@type": "Offer", "availability": "https://schema.org/InStock"},
}


class WhichPagesAreForSaleTests(unittest.TestCase):
    def test_the_marketplaces_are_recognised(self) -> None:
        for url in (
            "https://shopee.vn/abc-i.1.2",
            "https://www.lazada.vn/products/pdp-i1-s2.html",
            "https://shop.tiktok.com/vn/pdp/17334",
            "https://tiki.vn/x-p1.html",
        ):
            self.assertTrue(page_source.looks_like_shop(url), url)

    def test_a_news_site_is_not(self) -> None:
        self.assertFalse(page_source.looks_like_shop("https://vnexpress.net/bai-viet.html"))


class ReadingTheStructuredListingTests(unittest.TestCase):
    def test_the_product_block_is_pulled_out_whole(self) -> None:
        product = page_source.product_from_ld(_page([LAZADA_LIKE]))

        self.assertEqual(product["brand"], "X-men for Boss")
        self.assertEqual(product["sku"], "204631671")
        self.assertEqual(product["category"], "Làm đẹp > Nước hoa")

    def test_a_protocol_relative_image_becomes_fetchable(self) -> None:
        images = page_source.product_from_ld(_page([LAZADA_LIKE]))["images"]

        self.assertEqual(images[0], "https://cdn.test/a.jpg")

    def test_an_offer_without_a_price_yields_no_price(self) -> None:
        """Lazada's own offers block has no price field. Inventing one here
        would put a number into the pipeline that nobody ever read."""
        self.assertEqual(page_source.product_from_ld(_page([LAZADA_LIKE]))["price"], "")

    def test_a_page_with_no_product_block_gives_nothing(self) -> None:
        breadcrumb = {"@type": "BreadcrumbList", "itemListElement": []}

        self.assertEqual(page_source.product_from_ld(_page([breadcrumb])), {})


class WhenOnlyTheLinkPreviewSurvivesTests(unittest.TestCase):
    def test_the_og_tags_stand_in_for_the_listing(self) -> None:
        html = _page(metas={
            "og:title": "Điều khiển từ xa K-1028E",
            "og:description": "Mua giá tốt",
            "og:image": "//cdn.test/remote.jpg",
        })

        product = page_source.product_from_meta(html)

        self.assertEqual(product["name"], "Điều khiển từ xa K-1028E")
        self.assertEqual(product["images"], ["https://cdn.test/remote.jpg"])


class WhatCountsAsEnoughToStopAtTests(unittest.TestCase):
    def test_a_name_on_its_own_is_not_enough(self) -> None:
        """A bare name is what Shopee gives a signed-out visitor, and stopping
        there would hide that the price and the pictures were never read."""
        self.assertFalse(page_source._usable({"name": "Điều khiển từ xa", "price": "", "images": []}))

    def test_a_name_with_pictures_is(self) -> None:
        self.assertTrue(page_source._usable({"name": "X", "images": ["https://a.test/1.jpg"]}))

    def test_a_name_with_a_price_is(self) -> None:
        self.assertTrue(page_source._usable({"name": "X", "price": "285000"}))


class WhatTheModelIsHandedTests(unittest.TestCase):
    def test_a_missing_price_is_said_out_loud(self) -> None:
        """The single field a writer is most likely to fill in from nowhere."""
        described = page_source.describe({"name": "Nước hoa", "price": ""})

        self.assertIn("KHONG doc duoc gia", described)

    def test_a_price_that_was_read_is_not_warned_about(self) -> None:
        described = page_source.describe({"name": "Nước hoa", "price": "285000", "currency": "VND"})

        self.assertNotIn("KHONG doc duoc gia", described)
        self.assertIn("285000 VND", described)

    def test_when_the_page_was_read_is_part_of_the_record(self) -> None:
        """A price is only true on the day it was taken."""
        described = page_source.describe({"name": "X", "price": "1", "captured_at": "2026-09-27T00:00:00Z"})

        self.assertIn("2026-09-27", described)


class TheCheapestRouteThatAnswersTests(unittest.TestCase):
    def test_plain_http_is_enough_for_a_structured_listing(self) -> None:
        with mock.patch.object(page_source, "fetch_static", return_value=_page([LAZADA_LIKE])), \
                mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(page_source, "fetch_rendered") as browser:
            product = page_source.read_product("https://www.lazada.vn/products/x.html")

        browser.assert_not_called()
        self.assertEqual(product["route"], "http_jsonld")
        self.assertTrue(product["captured_at"])

    def test_a_page_that_needs_rendering_gets_the_browser(self) -> None:
        with mock.patch.object(page_source, "fetch_static", return_value=_page()), \
                mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(
                    page_source, "fetch_rendered",
                    return_value=(_page([LAZADA_LIKE]), "text", "https://shop.tiktok.com/vn/pdp/1"),
                ):
            product = page_source.read_product("https://shop.tiktok.com/vn/pdp/1")

        self.assertEqual(product["route"], "browser_jsonld")

    def test_the_routes_that_were_tried_are_recorded(self) -> None:
        """A caller holding a thin result needs to know which doors were shut."""
        with mock.patch.object(page_source, "fetch_static", return_value=_page()), \
                mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(page_source, "saved_profile", return_value=""), \
                mock.patch.object(page_source, "fetch_rendered", return_value=(_page(), "Cần đăng nhập", "https://shopee.vn/x-i.1.2")):
            product = page_source.read_product("https://shopee.vn/x-i.1.2")

        self.assertTrue(product["attempts"])
        self.assertEqual(product["route"], "browser_text")

    def test_a_site_that_will_not_load_at_all_raises(self) -> None:
        with mock.patch.object(page_source, "read_with_ai", return_value={}), mock.patch.object(
                page_source, "fetch_static", side_effect=page_source.PageSourceError("mất mạng"),
        ), mock.patch.object(
                page_source, "fetch_rendered", side_effect=page_source.PageSourceError("không mở được"),
        ):
            with self.assertRaises(page_source.PageSourceError):
                page_source.read_product("https://shopee.vn/x-i.1.2")


class AnArticlesOwnPicturesTests(unittest.TestCase):
    def test_the_lead_image_is_found(self) -> None:
        html = _page(
            [{"@type": "NewsArticle", "image": ["https://cdn.test/lead.jpg"]}],
            {"og:image": "https://cdn.test/social.jpg"},
        )

        self.assertEqual(
            page_source.article_images(html),
            ["https://cdn.test/lead.jpg", "https://cdn.test/social.jpg"],
        )

    def test_a_page_with_no_pictures_yields_none(self) -> None:
        self.assertEqual(page_source.article_images(_page()), [])

    def test_the_same_picture_twice_is_listed_once(self) -> None:
        html = _page(
            [{"@type": "NewsArticle", "image": "https://cdn.test/one.jpg"}],
            {"og:image": "https://cdn.test/one.jpg"},
        )

        self.assertEqual(page_source.article_images(html), ["https://cdn.test/one.jpg"])


if __name__ == "__main__":
    unittest.main()


class TellingAWallFromAPageTests(unittest.TestCase):
    """A marketplace serves an automated fetch a challenge rather than its
    content. Importing that challenge as a source is worse than failing: the
    project gets created, named "Security Check", and looks like it worked."""

    def test_the_usual_walls_are_recognised(self) -> None:
        for wall in (
            "Security Check",
            "Verify to continue: Drag the puzzle piece into place",
            "Please enable JavaScript on your browser.",
            "Cần đăng nhập",
            "Just a moment...",
        ):
            self.assertTrue(page_source.looks_like_bot_wall(wall), wall)

    def test_a_real_product_name_is_not_a_wall(self) -> None:
        for title in (
            "Điều khiển từ xa máy lạnh K-1028E | Shopee Việt Nam",
            "Nước hoa EDT X-Men for Boss Intense 49ml",
            "Bàn Chải Chà Giầy Dép Đa Năng",
        ):
            self.assertFalse(page_source.looks_like_bot_wall(title), title)

    def test_the_title_is_taken_from_og_before_the_tag(self) -> None:
        html = _page(metas={"og:title": "Tên sản phẩm thật"}) + "<title>Shopee Việt Nam</title>"

        self.assertEqual(page_source.page_title(html), "Tên sản phẩm thật")

    def test_a_page_with_only_a_title_tag_still_gives_one(self) -> None:
        self.assertEqual(
            page_source.page_title("<html><head><title>  Bài   viết </title></head></html>"),
            "Bài viết",
        )


class BeingSentSomewhereElseTests(unittest.TestCase):
    """A site that has decided you are a robot may answer by sending you to
    its home page rather than by saying no. The page then loads perfectly and
    publishes a real og:title - belonging to the home page. That is how a
    product import came back named "Shopee Việt Nam | Mua và Bán...".
    """

    def test_a_redirect_to_the_home_page_is_noticed(self) -> None:
        self.assertTrue(page_source.landed_elsewhere(
            "https://shopee.vn/San-pham-i.1006220775.41010972692", "https://shopee.vn/",
        ))

    def test_arriving_where_you_asked_is_not(self) -> None:
        self.assertFalse(page_source.landed_elsewhere(
            "https://shopee.vn/San-pham-i.1.2", "https://shopee.vn/San-pham-i.1.2",
        ))

    def test_a_tracking_query_added_on_arrival_is_not_a_redirect(self) -> None:
        self.assertFalse(page_source.landed_elsewhere(
            "https://www.lazada.vn/products/x.html",
            "https://www.lazada.vn/products/x.html?spm=a2o4n.homepage",
        ))

    def test_a_trailing_slash_is_not_a_redirect(self) -> None:
        self.assertFalse(page_source.landed_elsewhere(
            "https://vnexpress.net/khoa-hoc", "https://vnexpress.net/khoa-hoc/",
        ))


class ASignedInSessionPerSiteTests(unittest.TestCase):
    """Shopee does not refuse a robot, it sends one to the home page; a
    signed-in shopper is served the listing. One profile per site, so signing
    into Shopee does not require a TikTok account and a site that flags one
    profile does not reach the others."""

    def test_each_site_gets_its_own_profile(self) -> None:
        from youtube_monitor import shop_login

        shopee = shop_login.profile_dir("https://shopee.vn/x-i.1.2")
        tiktok = shop_login.profile_dir("shop.tiktok.com")

        self.assertNotEqual(shopee, tiktok)
        self.assertTrue(shopee.name.endswith("shopee_vn"))

    def test_a_bare_domain_and_a_full_link_mean_the_same_profile(self) -> None:
        from youtube_monitor import shop_login

        self.assertEqual(
            shop_login.profile_dir("shopee.vn"),
            shop_login.profile_dir("https://shopee.vn/San-pham-i.1.2?x=1"),
        )

    def test_a_directory_with_no_browser_state_is_not_a_profile(self) -> None:
        """What is answered here is "is there a profile worth using", not "are
        you signed in" - that cannot be told from outside, because opening a
        login page alone writes three hundred files and sets cookies."""
        import pathlib
        import tempfile

        from youtube_monitor import shop_login

        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(shop_login, "profile_dir", return_value=pathlib.Path(folder)):
                self.assertFalse(shop_login.has_profile("shopee.vn"))

    def test_a_profile_with_a_cookie_store_is_used(self) -> None:
        import pathlib
        import tempfile

        from youtube_monitor import shop_login

        with tempfile.TemporaryDirectory() as folder:
            store = pathlib.Path(folder) / "Default" / "Network"
            store.mkdir(parents=True)
            (store / "Cookies").write_bytes(b"sqlite")
            with mock.patch.object(shop_login, "profile_dir", return_value=pathlib.Path(folder)):
                self.assertTrue(shop_login.has_profile("shopee.vn"))

    def test_the_reader_picks_up_a_saved_session_without_being_told(self) -> None:
        with mock.patch.object(page_source, "saved_profile", return_value="C:/profile") as lookup, \
                mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(page_source, "fetch_static", return_value=_page([LAZADA_LIKE])):
            page_source.read_product("https://shopee.vn/x-i.1.2")

        lookup.assert_called_once()

    def test_an_explicit_profile_is_not_overridden(self) -> None:
        with mock.patch.object(page_source, "saved_profile") as lookup, \
                mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(page_source, "fetch_static", return_value=_page([LAZADA_LIKE])):
            page_source.read_product("https://shopee.vn/x-i.1.2", profile_dir="C:/chosen")

        lookup.assert_not_called()


class LettingTheReaderSeeWhatTheMarkupCannotTests(unittest.TestCase):
    """Lazada's own JSON-LD carries an Offer with no price field in it, Shopee
    answers a script-only shell and TikTok a captcha - so the price, the rating
    and the review count exist nowhere in the HTML the app can reach. The CLI's
    own web reader gets them. Measured: 280.000₫, 4.9 stars, 1073 reviews."""

    MARKUP = {"name": "Nước hoa", "brand": "X-men", "images": ["https://cdn/1.jpg"], "price": ""}
    READ = {
        "readable": True, "name": "Nước hoa EDT", "price": "280.000", "currency": "₫",
        "rating": "4.9", "review_count": "1073", "brand": "", "note": "Đọc được",
    }

    def test_the_reader_fills_the_price_the_markup_never_had(self) -> None:
        merged = page_source._merge_reader(dict(self.MARKUP), self.READ)

        self.assertEqual(merged["price"], "280.000")
        self.assertEqual(merged["rating"], "4.9")
        self.assertEqual(merged["review_count"], "1073")

    def test_the_markup_keeps_what_it_stated_itself(self) -> None:
        """JSON-LD carries the pictures and the brand exactly, with no model
        in the loop. A reader's summary must not overwrite that."""
        merged = page_source._merge_reader(dict(self.MARKUP), self.READ)

        self.assertEqual(merged["brand"], "X-men")
        self.assertEqual(merged["name"], "Nước hoa")
        self.assertEqual(merged["images"], ["https://cdn/1.jpg"])

    def test_the_readers_own_caveat_is_carried_along(self) -> None:
        merged = page_source._merge_reader(dict(self.MARKUP), self.READ)

        self.assertEqual(merged["reader_note"], "Đọc được")

    def test_a_reader_that_could_not_read_changes_nothing(self) -> None:
        self.assertEqual(page_source._merge_reader(dict(self.MARKUP), {}), self.MARKUP)

    def test_a_page_the_reader_says_is_blocked_is_not_used(self) -> None:
        """readable=false is the reader telling us it hit a wall; treating
        its empty fields as facts would be worse than having none."""
        with mock.patch(
            "youtube_monitor.claude_code_bridge.call_claude_code_json",
            return_value={"readable": False, "note": "captcha"},
        ):
            self.assertEqual(page_source.read_with_ai("https://shopee.vn/x-i.1.2"), {})

    def test_a_reader_that_is_not_installed_is_not_a_failure(self) -> None:
        """Whatever the markup gave is still better than nothing."""
        with mock.patch(
            "youtube_monitor.claude_code_bridge.call_claude_code_json",
            side_effect=RuntimeError("chưa cài"),
        ):
            self.assertEqual(page_source.read_with_ai("https://shopee.vn/x-i.1.2"), {})

    def test_the_web_tool_is_opened_only_for_this_one_job(self) -> None:
        """Every other caller keeps the no-tools posture: a script writer has
        no business browsing."""
        with mock.patch(
            "youtube_monitor.claude_code_bridge.call_claude_code_json",
            return_value={"readable": True, "name": "X"},
        ) as call:
            page_source.read_with_ai("https://www.lazada.vn/products/x.html")

        self.assertTrue(call.call_args.kwargs["allow_web"])


class TheNameAMarketplaceWritesIntoItsOwnUrlTests(unittest.TestCase):
    """Shopee puts the listing's title in the path, so a page that refuses to
    load still says what it is selling. Not the price - but a source named
    after the product beats one named "Shopee Việt Nam | Mua và Bán Trên Ứng
    Dụng Di Động", which is what reading the home page's title produced."""

    def test_a_shopee_path_carries_the_product_name(self) -> None:
        name = page_source.name_from_url(
            "https://shopee.vn/Tai-Nghe-S10-M%C3%A0u-%C4%90en-Mini-Kh%C3%B4ng-D%C3%A2y-i.196261835.29134843988"
        )

        self.assertEqual(name, "Tai Nghe S10 Màu Đen Mini Không Dây")

    def test_the_item_identifier_is_not_part_of_the_name(self) -> None:
        self.assertNotIn("196261835", page_source.name_from_url(
            "https://shopee.vn/Tai-Nghe-S10-i.196261835.29134843988"
        ))

    def test_a_path_of_identifiers_is_not_a_name(self) -> None:
        """Lazada's path is "pdp-i204631671-s254952397" - an identifier
        wearing the shape of a title. Returning it would put a row called
        "pdp i204631671" in the library."""
        self.assertEqual(
            page_source.name_from_url("https://www.lazada.vn/products/pdp-i204631671-s254952397.html"), ""
        )

    def test_a_path_of_digits_is_not_a_name(self) -> None:
        self.assertEqual(page_source.name_from_url("https://shop.tiktok.com/vn/pdp/1733450240927368413"), "")

    def test_a_bare_host_has_no_name_in_it(self) -> None:
        self.assertEqual(page_source.name_from_url("https://shopee.vn/"), "")


class WhenTheBrowserIsSentToTheHomePageTests(unittest.TestCase):
    def test_the_home_pages_title_never_becomes_the_product(self) -> None:
        home = _page(metas={"og:title": "Shopee Việt Nam | Mua và Bán Trên Ứng Dụng Di Động"})

        with mock.patch.object(page_source, "read_with_ai", return_value={}), \
                mock.patch.object(page_source, "saved_profile", return_value=""), \
                mock.patch.object(page_source, "fetch_static", return_value=_page()), \
                mock.patch.object(
                    page_source, "fetch_rendered", return_value=(home, "Cần đăng nhập", "https://shopee.vn/"),
                ):
            product = page_source.read_product(
                "https://shopee.vn/Tai-Nghe-S10-M%C3%A0u-%C4%90en-i.196261835.29134843988"
            )

        self.assertNotIn("Shopee Việt Nam", product["name"])
        self.assertEqual(product["name"], "Tai Nghe S10 Màu Đen")
        self.assertEqual(product["route"], "url_slug")
        self.assertIn("bị chuyển sang trang khác", " ".join(product["attempts"]))
