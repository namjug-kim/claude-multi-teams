from cmt import claude_screen


_SURVEY = (
    "  ⏺ done\n\n"
    "How is Claude doing this session? (optional)\n"
    "1: Bad   2: Fine   3: Good   0: Dismiss\n"
    "> \n"
)
_NORMAL = "  ⏺ ok\n\n│ > write a test │\n  ? for shortcuts\n"


def test_detects_feedback_survey() -> None:
    assert claude_screen.is_feedback_survey(_SURVEY) is True
    assert claude_screen.is_feedback_survey(_NORMAL) is False


def test_dismiss_sends_keys_only_when_survey_present() -> None:
    sent: list[tuple] = []
    acted = claude_screen.dismiss_survey_if_present(
        capture=lambda: _SURVEY, send_keys=lambda *k: sent.append(k)
    )
    assert acted is True
    assert sent == [("0", "Enter")]


def test_dismiss_is_noop_without_survey() -> None:
    sent: list[tuple] = []
    acted = claude_screen.dismiss_survey_if_present(
        capture=lambda: _NORMAL, send_keys=lambda *k: sent.append(k)
    )
    assert acted is False
    assert sent == []
