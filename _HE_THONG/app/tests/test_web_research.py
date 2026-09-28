"""Letting whoever is directing look something up.

Of the tools an orchestrator could reach, none searched for anything: it was
told to research a topic and also told not to invent facts, with nothing in
between. These tests cover what a lookup returns, and what it does when the
lookup fails - which must never be a run that stops.
"""

from __future__ import annotations

import unittest
from unittest import mock

import httpx

from youtube_monitor import web_research


PAGE = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fvi.wikipedia.org%2Fwiki%2FAI&amp;rut=x">
    Lịch sử <b>trí tuệ nhân tạo</b>
  </a>
  <a class="result__snippet" href="#">Ngành này bắt đầu từ hội nghị <b>Dartmouth</b> năm 1956.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fai&amp;rut=y">Tổng quan AI</a>
  <a class="result__snippet" href="#">Bài viết tổng hợp.</a>
</div>
"""


def _response(text: str = PAGE, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, request=httpx.Request("GET", "https://example.test"))


class WhatALookupReturnsTests(unittest.TestCase):
    def test_the_real_site_is_returned_not_the_redirect(self) -> None:
        """The caller wants somewhere to go, not a tracking hop."""
        with mock.patch.object(web_research.httpx, "get", return_value=_response()):
            results = web_research.search("trí tuệ nhân tạo")

        self.assertEqual(results[0]["url"], "https://vi.wikipedia.org/wiki/AI")
        self.assertEqual(results[0]["source"], "vi.wikipedia.org")

    def test_markup_is_stripped_out_of_titles_and_snippets(self) -> None:
        with mock.patch.object(web_research.httpx, "get", return_value=_response()):
            results = web_research.search("ai")

        self.assertEqual(results[0]["title"], "Lịch sử trí tuệ nhân tạo")
        self.assertIn("Dartmouth năm 1956", results[0]["snippet"])

    def test_the_limit_is_honoured(self) -> None:
        with mock.patch.object(web_research.httpx, "get", return_value=_response()):
            self.assertEqual(len(web_research.search("ai", limit=1)), 1)

    def test_an_empty_query_never_reaches_the_network(self) -> None:
        with mock.patch.object(web_research.httpx, "get", side_effect=AssertionError("không được gọi")) as call:
            self.assertEqual(web_research.search("   "), [])
        call.assert_not_called()


class WhenTheLookupFailsTests(unittest.TestCase):
    def test_a_network_failure_returns_nothing_instead_of_raising(self) -> None:
        """A video does not become unmakeable because a search engine was
        unreachable."""
        with mock.patch.object(web_research.httpx, "get", side_effect=httpx.ConnectError("offline")):
            self.assertEqual(web_research.search("ai"), [])

    def test_a_refusal_from_the_site_is_not_an_exception_either(self) -> None:
        with mock.patch.object(web_research.httpx, "get", return_value=_response("", status=429)):
            self.assertEqual(web_research.search("ai"), [])

    def test_an_empty_result_says_plainly_that_nothing_was_researched(self) -> None:
        """A model handed an empty list otherwise fills the gap from memory
        and presents it as research."""
        summary = web_research.summarise("ai", [])

        self.assertEqual(summary["count"], 0)
        self.assertIn("Đừng coi đây là đã nghiên cứu", summary["note"])

    def test_a_good_result_still_says_it_is_only_a_pointer(self) -> None:
        with mock.patch.object(web_research.httpx, "get", return_value=_response()):
            summary = web_research.summarise("ai", web_research.search("ai"))

        self.assertEqual(summary["sources"], ["example.com", "vi.wikipedia.org"])
        self.assertIn("không phải nội dung đã kiểm chứng", summary["note"])


if __name__ == "__main__":
    unittest.main()


class WhenOneSourceWillNotAnswerTests(unittest.TestCase):
    """One page shape meant one point of failure: the result pattern stops
    matching and the step reports "researched nothing" while the engine is
    answering perfectly well."""

    def test_the_second_source_is_tried_when_the_first_returns_nothing(self) -> None:
        backup = [{"title": "B", "snippet": "s", "url": "https://b.test/x", "source": "b.test"}]

        with mock.patch.object(web_research, "_duckduckgo", return_value="<html></html>"), \
                mock.patch.object(web_research, "_duckduckgo_lite", return_value=backup) as lite:
            found = web_research.search("trái đất", limit=3)

        lite.assert_called_once()
        self.assertEqual(found, backup)

    def test_the_first_source_answering_stops_there(self) -> None:
        primary = [{"title": "A", "snippet": "s", "url": "https://a.test/x", "source": "a.test"}]

        with mock.patch.object(web_research, "_duckduckgo", return_value="x"), \
                mock.patch.object(web_research, "_parse_duckduckgo", return_value=primary), \
                mock.patch.object(web_research, "_duckduckgo_lite") as lite:
            found = web_research.search("trái đất", limit=3)

        lite.assert_not_called()
        self.assertEqual(found, primary)

    def test_every_source_failing_is_still_an_empty_list(self) -> None:
        """A video does not become unmakeable because search is unreachable."""
        with mock.patch.object(web_research, "_duckduckgo", side_effect=httpx.ConnectError("no")), \
                mock.patch.object(web_research, "_duckduckgo_lite", side_effect=httpx.ConnectError("no")), \
                mock.patch.object(web_research, "_wikipedia", side_effect=httpx.ConnectError("no")):
            self.assertEqual(web_research.search("trái đất"), [])


class ReadingWhatWasFoundTests(unittest.TestCase):
    """Titles and snippets are a table of contents. A writer handed only those
    still has to invent the substance, which is what this step exists to
    prevent."""

    def test_the_top_results_are_opened_and_their_text_attached(self) -> None:
        found = [
            {"title": "A", "snippet": "s", "url": "https://a.test/1", "source": "a.test"},
            {"title": "B", "snippet": "s", "url": "https://b.test/2", "source": "b.test"},
        ]

        with mock.patch.object(web_research, "_duckduckgo", return_value="x"), \
                mock.patch.object(web_research, "_parse_duckduckgo", return_value=found), \
                mock.patch.object(web_research, "read_page", return_value="Nội dung thật") as read:
            results = web_research.search("trái đất", limit=2, read_pages=1)

        self.assertEqual(read.call_count, 1)
        self.assertEqual(results[0]["text"], "Nội dung thật")
        self.assertNotIn("text", results[1])

    def test_a_wikipedia_result_is_read_through_the_api_not_scraped(self) -> None:
        """Scraping the article earns a 403; the API is what it asks tools to
        use, and it hands over cleaner text than stripping tags would."""
        found = [{"title": "Lịch sử Trái Đất", "snippet": "s",
                  "url": "https://vi.wikipedia.org/wiki/X", "source": "vi.wikipedia.org"}]

        with mock.patch.object(web_research, "_duckduckgo", return_value="x"), \
                mock.patch.object(web_research, "_parse_duckduckgo", return_value=found), \
                mock.patch.object(web_research, "_wikipedia_extract", return_value="Bài viết") as api, \
                mock.patch.object(web_research, "read_page") as scrape:
            results = web_research.search("trái đất", limit=1, read_pages=1)

        api.assert_called_once()
        scrape.assert_not_called()
        self.assertEqual(results[0]["text"], "Bài viết")

    def test_a_page_that_will_not_open_leaves_the_result_alone(self) -> None:
        found = [{"title": "A", "snippet": "s", "url": "https://a.test/1", "source": "a.test"}]

        with mock.patch.object(web_research, "_duckduckgo", return_value="x"), \
                mock.patch.object(web_research, "_parse_duckduckgo", return_value=found), \
                mock.patch.object(web_research, "read_page", return_value=""):
            results = web_research.search("trái đất", limit=1, read_pages=1)

        self.assertNotIn("text", results[0])

    def test_scripts_and_styles_are_not_part_of_the_readable_text(self) -> None:
        page = "<html><script>var a=1;</script><p>Trái Đất 4,5 tỉ năm.</p><style>x{}</style></html>"
        response = mock.MagicMock(status_code=200, text=page, headers={"content-type": "text/html"})
        response.raise_for_status.return_value = None

        with mock.patch.object(web_research.httpx, "get", return_value=response):
            body = web_research.read_page("https://a.test/1")

        self.assertIn("Trái Đất 4,5 tỉ năm.", body)
        self.assertNotIn("var a=1", body)
