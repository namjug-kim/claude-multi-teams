"""Tests for the generic selection-modal parser."""

from __future__ import annotations

from cmt.modal import detect, select_keys


def test_no_modal_returns_none() -> None:
    assert detect("just some output\nno options here") is None


def test_single_numbered_line_is_not_a_modal() -> None:
    # A lone "1." in prose must not be mistaken for a choice list.
    assert detect("Step 1. do the thing first\nthen continue") is None


def test_parses_trust_modal() -> None:
    m = detect(
        "Do you trust the contents of this directory?\n"
        "› 1. Yes, continue\n"
        "  2. No, quit"
    )
    assert m is not None
    assert m.options == ("Yes, continue", "No, quit")
    assert m.highlighted == 1
    assert m.title == "Do you trust the contents of this directory?"


def test_parses_update_modal_and_skips_url_and_version_for_title() -> None:
    m = detect(
        "✨ Update available! 0.134.0 → 0.135.0\n"
        "Release notes: https://github.com/openai/codex/releases/latest\n\n"
        "  1. Update now (runs `npm install -g @openai/codex`)\n"
        "› 2. Skip\n"
        "  3. Skip until next version\n\n"
        "Press enter to continue"
    )
    assert m is not None
    assert m.options[1] == "Skip"
    assert m.highlighted == 2
    assert "Update available!" in m.title
    assert m.footer == "Press enter to continue"


def test_index_of_matches_by_content_case_insensitive() -> None:
    m = detect(
        "Hooks need review\n"
        "› 1. Review hooks\n"
        "  2. Trust all and continue\n"
        "  3. Continue without trusting (hooks won't run)"
    )
    assert m is not None
    assert m.index_of("trust all") == 2
    assert m.index_of("Review") == 1
    assert m.index_of("nonexistent") is None


def test_non_contiguous_numbering_stops_the_list() -> None:
    # "2." missing -> only the leading contiguous run counts; here just "1." so
    # fewer than two options -> not a modal.
    assert detect("› 1. only one\n  3. skipped two") is None


def test_select_keys_is_digit_then_enter() -> None:
    assert select_keys(2) == ("2", "Enter")


def test_render_round_trips_basic_shape() -> None:
    m = detect("Pick one\n› 1. A\n  2. B\nPress enter to confirm")
    assert m is not None
    out = m.render()
    assert "› 1. A" in out
    assert "  2. B" in out
    assert "Pick one" in out
