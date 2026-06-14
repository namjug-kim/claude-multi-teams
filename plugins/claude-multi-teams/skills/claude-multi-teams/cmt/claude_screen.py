"""Screen-based handling for claude's between-turn nags.

claude's turn state lives in the jsonl (terminal stop_reason / a parked
AskUserQuestion — see ``strategies``). The one thing the jsonl does *not*
surface is the periodic feedback survey claude overlays on the input area
between turns:

    How is Claude doing this session? (optional)
    1: Bad   2: Fine   3: Good   0: Dismiss
    > █

It is the direct analogue of agy's "Help us improve" survey, which cmt already
auto-dismisses. Left up, it occupies the composer: the next ``ask`` types into
the survey instead of starting a turn, and the pane sits at an idle input prompt
that no wait ever resolves. We dismiss it (``0`` = Dismiss) wherever we touch the
pane. Permission-skip flags already imply auto-handling non-security UX; a
feedback survey qualifies.
"""

from __future__ import annotations

from typing import Callable

SURVEY_MARKER = "How is Claude doing this session?"
# "0: Dismiss" — press the digit, then Enter, mirroring the agy survey + modal
# selection convention (digit moves/selects, Enter confirms).
SURVEY_DISMISS_KEYS = ("0", "Enter")


def is_feedback_survey(screen: str) -> bool:
    """True if claude's feedback survey is currently overlaid on the pane."""
    return SURVEY_MARKER in screen


def dismiss_survey_if_present(
    capture: Callable[[], str],
    send_keys: Callable[..., None],
) -> bool:
    """Dismiss the feedback survey if it is up. Returns True if it acted.

    Read-then-act: only sends keys when the survey marker is on screen, so a
    stray ``0`` can never leak into a normal composer.
    """
    if is_feedback_survey(capture()):
        send_keys(*SURVEY_DISMISS_KEYS)
        return True
    return False
