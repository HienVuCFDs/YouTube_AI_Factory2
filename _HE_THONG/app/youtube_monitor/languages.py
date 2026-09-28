"""Which language the app writes in, and how fast that language is spoken.

Two separate things used to be fixed to Vietnamese: the language the AI wrote
its analysis and scripts in, and the speaking rate used to decide how many
words a script needs to fill its running time. Changing only the first would
produce an English script sized for Vietnamese, which comes out roughly a
quarter too long - so the rate travels with the language choice.

Only the Vietnamese rate is measured: it was taken from VoxCPM reading real
scripts in this app. The rest are ordinary narration rates for an unhurried
documentary read, and should be corrected against real output rather than
trusted as precise.
"""

from __future__ import annotations

from typing import Any

DEFAULT_LANGUAGE = "vi"

LANGUAGES: dict[str, dict[str, Any]] = {
    "vi": {
        "label": "Tiếng Việt",
        "name": "tieng Viet",
        "english_name": "Vietnamese",
        # Measured against VoxCPM in this app; Vietnamese is counted in
        # syllable-separated tokens, not multi-syllable words.
        "tokens_per_second": 3.2,
        "min_tokens_per_second": 3.0,
        "unit": "âm tiết",
    },
    "en": {
        "label": "Tiếng Anh",
        "name": "tieng Anh",
        "english_name": "English",
        # ~150 words per minute, the usual pace for narration.
        "tokens_per_second": 2.5,
        "min_tokens_per_second": 2.3,
        "unit": "từ",
    },
    "zh": {
        "label": "Tiếng Trung",
        "name": "tieng Trung",
        "english_name": "Chinese",
        "tokens_per_second": 4.0,
        "min_tokens_per_second": 3.6,
        "unit": "chữ",
    },
    "ja": {
        "label": "Tiếng Nhật",
        "name": "tieng Nhat",
        "english_name": "Japanese",
        "tokens_per_second": 5.0,
        "min_tokens_per_second": 4.5,
        "unit": "âm tiết",
    },
    "ko": {
        "label": "Tiếng Hàn",
        "name": "tieng Han",
        "english_name": "Korean",
        "tokens_per_second": 4.2,
        "min_tokens_per_second": 3.8,
        "unit": "âm tiết",
    },
    "es": {
        "label": "Tiếng Tây Ban Nha",
        "name": "tieng Tay Ban Nha",
        "english_name": "Spanish",
        "tokens_per_second": 2.8,
        "min_tokens_per_second": 2.5,
        "unit": "từ",
    },
    "de": {
        "label": "Tiếng Đức",
        "name": "tieng Duc",
        "english_name": "German",
        "tokens_per_second": 2.3,
        "min_tokens_per_second": 2.1,
        "unit": "từ",
    },
    "fr": {
        "label": "Tiếng Pháp",
        "name": "tieng Phap",
        "english_name": "French",
        "tokens_per_second": 2.6,
        "min_tokens_per_second": 2.4,
        "unit": "từ",
    },
}


def resolve(code: str | None) -> dict[str, Any]:
    """The language record for a code, falling back to Vietnamese.

    An unknown code returns Vietnamese rather than raising: a stale value in
    a saved session should not stop a script being written.
    """
    return LANGUAGES.get(str(code or "").strip().lower(), LANGUAGES[DEFAULT_LANGUAGE])


def label(code: str | None) -> str:
    return str(resolve(code)["label"])


def instruction(code: str | None) -> str:
    """The line that tells a model which language to answer in."""
    record = resolve(code)
    return (
        f"NGON NGU DAU RA: viet TOAN BO ket qua bang {record['name']} ({record['english_name']}), "
        "ke ca khi nguon dung ngon ngu khac.\n"
        # Quoted lines are the part a model most often leaves in the source
        # language, on the reasoning that a quote should be verbatim. Here the
        # whole point is that a Vietnamese writer can read them.
        "LOI THOAI cung phai DICH sang ngon ngu nay - khong duoc giu nguyen tieng goc, "
        "khong duoc phien am. Chi giu nguyen ten rieng, dia danh va con so."
    )
