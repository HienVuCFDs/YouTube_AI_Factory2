"""Names and numbers a retelling states that its source never did."""

from __future__ import annotations

from youtube_monitor.fidelity_guard import numbers, proper_nouns, unsourced_details

SOURCE = (
    "Ngày xưa có hai anh em họ Cao, người anh tên Tân, người em tên Lang. "
    "Lang bỏ nhà ra đi, đến bờ suối thì chết, hoá thành tảng đá. "
    "Tân đi tìm em, cũng chết, hoá thành cây cau. "
    "Vua Hùng đi qua, từ đó người Việt có tục ăn trầu trong lễ cưới."
)


def test_a_retelling_worded_completely_differently_passes() -> None:
    """Changing how it is told is the point; only content is fixed."""
    retelling = (
        "Thuở ấy, nhà họ Cao có hai người con trai giống nhau như đúc. "
        "Người anh là Tân, người em là Lang. "
        "Lang buồn mà bỏ đi, tới bờ suối thì kiệt sức, thân hoá tảng đá. "
        "Tân tìm em, cũng nằm lại đó, hoá thành cây cau. "
        "Chuyện tới tai vua Hùng, và người Việt có tục ăn trầu trong lễ cưới từ đấy."
    )

    result = unsourced_details(SOURCE, retelling)

    assert result["names"] == []
    assert result["numbers"] == []


def test_a_swapped_historical_figure_is_caught() -> None:
    """Vua Hung becoming Le Loi is the exact failure this exists for."""
    retelling = "Vua Lê Lợi đi qua nghe chuyện, từ đó người Việt có tục ăn trầu."

    assert "Lợi" in unsourced_details(SOURCE, retelling)["names"]


def test_an_invented_character_is_caught() -> None:
    retelling = "Người anh bỏ nhà ra đi cùng con chó nhỏ tên Vện."

    assert "Vện" in unsourced_details(SOURCE, retelling)["names"]


def test_a_name_the_source_does_have_is_not_flagged() -> None:
    """Both characters appear in the source; using them is required, not a fault."""
    retelling = "Tân đi tìm Lang khắp nơi."

    assert unsourced_details(SOURCE, retelling)["names"] == []


def test_a_name_is_accepted_even_when_the_source_only_starts_a_sentence_with_it() -> None:
    """'Lang bo nha ra di' - sentence-initial, so undetectable as a proper noun
    in the source, yet plainly present. Matching is on raw text for that reason."""
    result = unsourced_details("Lang bỏ nhà ra đi.", "Chàng trai tên Lang đã bỏ đi.")

    assert result["names"] == []


def test_tone_marks_and_case_cannot_hide_a_name_that_is_present() -> None:
    result = unsourced_details("nguoi anh ten TAN", "Người anh tên Tân.")

    assert result["names"] == []


def test_a_number_the_source_never_gave_is_caught() -> None:
    result = unsourced_details("Ông sống ở đó nhiều năm.", "Ông sống ở đó suốt 47 năm.")

    assert result["numbers"] == ["47"]


def test_the_same_number_written_with_separators_still_matches() -> None:
    result = unsourced_details("Thiệt hại 1.000 tỷ đồng.", "Thiệt hại 1,000 tỷ đồng.")

    assert result["numbers"] == []


def test_leaving_something_out_is_not_a_fault() -> None:
    """A retelling is shorter than its source; omission is compression."""
    result = unsourced_details(SOURCE, "Hai anh em họ Cao thương nhau lắm.")

    assert result["names"] == []
    assert result["numbers"] == []


def test_a_sentence_opening_word_is_not_mistaken_for_a_name() -> None:
    """Vietnamese capitalises every sentence start, which carries no signal."""
    assert proper_nouns("Nhưng rồi mọi chuyện đổi khác. Và họ chia tay.") == []


def test_titles_are_stripped_so_the_name_itself_is_compared() -> None:
    """'Vua Hung' should yield 'Hung' - the title is not the name."""
    found = [word.lower() for word in proper_nouns("Chuyện đến tai Vua Hùng ngay hôm ấy.")]

    assert "hùng" in found
    assert "vua" not in found


def test_numbers_are_reported_once_each() -> None:
    assert numbers("Có 3 người, rồi 3 người nữa, tổng 6.") == ["3", "6"]
