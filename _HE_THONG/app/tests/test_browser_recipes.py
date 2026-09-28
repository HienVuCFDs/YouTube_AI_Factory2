"""Driving a chat page without spending a model call on every click.

The extension asked the orchestrator what to do thirty times per picture, so
the whole provider died whenever no text model was reachable - which is what
the recorded failures say: ten refusals on ChatGPT web, three on Gemini web,
all of them "Không có AI được phép thực hiện công đoạn orchestration".
"""

from __future__ import annotations

import unittest

from youtube_monitor import browser_recipes


GOAL = "\n".join([
    "Tao MOT ANH TINH bang ChatGPT (giao dien chat web).",
    "",
    "PROMPT CAN GUI:",
    "A lighthouse at dusk, oil painting",
])


def _composer(**extra: object) -> list[dict[str, object]]:
    return [
        {"i": 0, "tag": "div", "id": "prompt-textarea", "role": "textbox", "cls": "ProseMirror",
         "label": "", "text": "", "disabled": False, "w": 700, "h": 60, **extra},
        {"i": 1, "tag": "button", "testid": "send-button", "label": "Send prompt",
         "text": "", "cls": "", "id": "", "disabled": False, "w": 36, "h": 36},
    ]


def _image(index: int, src: str, size: int = 512) -> dict[str, object]:
    return {"i": index, "tag": "img", "text": f"src={src}", "label": "", "cls": "", "id": "",
            "testid": "", "disabled": False, "w": size, "h": size}


class KnownPagesAreDrivenWithoutAModelTests(unittest.TestCase):
    def setUp(self) -> None:
        browser_recipes.forget_run(GOAL, "https://chatgpt.com/")

    def test_the_first_step_types_the_prompt_and_sends_it(self) -> None:
        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        )

        assert action is not None
        self.assertEqual(action["action"], "type")
        self.assertEqual(action["index"], 0)
        self.assertEqual(action["text"], "A lighthouse at dusk, oil painting")
        self.assertEqual(action["then"], [{"action": "click", "index": 1}, {"action": "wait"}])
        self.assertEqual(action["decided_by"], "recipe")

    def test_a_disabled_send_button_is_waited_out_rather_than_clicked(self) -> None:
        elements = _composer()
        elements[1]["disabled"] = True

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=elements,
            history=["1. type(0) — go prompt"], step=2,
        )

        assert action is not None
        self.assertEqual(action["action"], "wait")

    def test_a_sent_prompt_waits_while_the_picture_is_drawn(self) -> None:
        browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        )

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(),
            history=["1. type(0) — go prompt", "   + click(1)"], step=2,
        )

        assert action is not None
        self.assertEqual(action["action"], "wait")

    def test_a_picture_drawn_after_sending_finishes_the_run(self) -> None:
        browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        )

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/",
            elements=[*_composer(), _image(2, "https://files/new.png")],
            history=["1. type(0) — go prompt", "   + click(1)"], step=3,
        )

        assert action is not None
        self.assertEqual(action["action"], "done")
        self.assertEqual(action["index"], 2)

    def test_a_picture_that_was_already_there_is_never_the_result(self) -> None:
        """A chat page is full of earlier pictures from earlier scenes."""
        before = [*_composer(), _image(2, "https://files/old.png")]
        browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=before, history=[], step=1,
        )

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=before,
            history=["1. type(0) — go prompt", "   + click(1)"], step=2,
        )

        assert action is not None
        self.assertEqual(action["action"], "wait")

    def test_a_follow_up_that_failed_does_not_count_as_a_click(self) -> None:
        """Otherwise the prompt sits typed and unsent for the rest of the run."""
        browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        )

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(),
            history=["1. type(0) — go prompt", "   + click(1): dung lai - khong bam duoc"], step=2,
        )

        assert action is not None
        self.assertEqual(action["action"], "click")
        self.assertEqual(action["index"], 1)

    def test_a_reference_image_is_attached_before_the_prompt_is_typed(self) -> None:
        goal = GOAL.replace(
            "PROMPT CAN GUI:",
            "Co san mot anh tham chieu: khi thay o dinh kem file, dung attach_image.\n\nPROMPT CAN GUI:",
        )
        browser_recipes.forget_run(goal, "https://chatgpt.com/")
        elements = [*_composer(), {"i": 2, "tag": "input", "text": "O DINH KEM FILE", "label": "",
                                   "cls": "", "id": "", "testid": "", "disabled": False, "w": 1, "h": 1}]

        action = browser_recipes.next_action(
            goal=goal, url="https://chatgpt.com/", elements=elements, history=[], step=1,
        )

        assert action is not None
        self.assertEqual(action["action"], "attach_image")
        self.assertEqual(action["index"], 2)


class WhatIsHandedBackToTheModelTests(unittest.TestCase):
    def test_flow_and_meta_keep_the_model_driven_loop(self) -> None:
        """Their composer hides image mode and video mode behind tabs, and a
        wrong click there spends the user's paid generations."""
        for url in ("https://labs.google/fx/tools/flow", "https://www.meta.ai/"):
            with self.subTest(url=url):
                self.assertIsNone(browser_recipes.recipe_for(url))
                self.assertIsNone(browser_recipes.next_action(
                    goal=GOAL, url=url, elements=_composer(), history=[], step=1,
                ))

    def test_a_composer_that_cannot_be_found_is_handed_over(self) -> None:
        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/",
            elements=[{"i": 0, "tag": "button", "label": "Đăng nhập", "text": "", "cls": "",
                       "id": "", "testid": "", "disabled": False, "w": 100, "h": 40}],
            history=[], step=1,
        )

        self.assertIsNone(action)

    def test_waiting_far_too_long_is_handed_over_to_the_model(self) -> None:
        """A page stuck this long is showing something that needs reading -
        a refusal, a usage limit, a login wall - and reading is the model's job."""
        browser_recipes.forget_run(GOAL, "https://chatgpt.com/")
        browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        )
        history = ["1. type(0) — go prompt", "   + click(1)"]
        history += [f"{index}. wait — cho anh" for index in range(2, 2 + browser_recipes.MAX_WAITS)]

        action = browser_recipes.next_action(
            goal=GOAL, url="https://chatgpt.com/", elements=_composer(), history=history, step=20,
        )

        self.assertIsNone(action)

    def test_a_goal_without_a_prompt_is_not_guessed_at(self) -> None:
        self.assertIsNone(browser_recipes.next_action(
            goal="Tao anh dep", url="https://chatgpt.com/", elements=_composer(), history=[], step=1,
        ))


class TheEndpointAnswersWithoutSpendingAModelCallTests(unittest.TestCase):
    """Measured on the running app: one model-decided step took 41.8 seconds,
    and a picture can take thirty of them."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        from youtube_monitor.main import app

        cls._client_cm = TestClient(app)
        cls.client = cls._client_cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._client_cm.__exit__(None, None, None)

    def _post(self, **overrides: object) -> dict:
        payload = {
            "goal": GOAL,
            "url": "https://chatgpt.com/",
            "viewport": {"w": 1280, "h": 800},
            "elements": _composer(),
            "page_text": "",
            "history": [],
            "step": 1,
            **overrides,
        }
        response = self.client.post("/api/orchestrator/browser-action", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_a_known_chat_page_is_answered_by_the_recipe(self) -> None:
        from unittest.mock import patch

        browser_recipes.forget_run(GOAL, "https://chatgpt.com/")
        with patch("youtube_monitor.main._call_orchestrator_json") as model:
            body = self._post()

        model.assert_not_called()
        self.assertEqual(body["action"], "type")
        self.assertEqual(body["decided_by"], "recipe")

    def test_the_follow_up_steps_reach_the_browser(self) -> None:
        """They are what save the round trip, and they used to be dropped
        here although both the schema and the extension carry them."""
        browser_recipes.forget_run(GOAL, "https://chatgpt.com/")

        body = self._post()

        self.assertEqual(body["then"], [{"action": "click", "index": 1, "text": ""}, {"action": "wait", "index": None, "text": ""}])

    def test_an_unknown_page_still_goes_to_the_model(self) -> None:
        from unittest.mock import patch

        with patch(
            "youtube_monitor.main._call_orchestrator_json",
            return_value={"action": "wait", "reason": "để model quyết"},
        ) as model:
            body = self._post(url="https://www.meta.ai/")

        model.assert_called_once()
        self.assertEqual(body["decided_by"], "model")


if __name__ == "__main__":
    unittest.main()
