# 0001 — Python as the only runtime

**Status:** Accepted (2026-05-27)

## Context

The first generation of this project was a tangle of bash scripts driving
``tmux send-keys`` and tailing jsonl. Adding a single state-related rule
(e.g. "after the most recent ask, baseline = current jsonl size") meant
threading another shell variable through five files. It worked, but every
change burned an hour on shell quoting and array semantics.

Before the rewrite we briefly considered:

- **Continuing in shell** — known territory, no new dependency to install.
- **Rust** — [herdr](https://github.com/ogulcancelik/herdr) demonstrates the
  shape of a CLI that drives tmux for a similar workflow. Fast, single binary.
- **Python** — readable, batteries-included, already on every dev machine
  we care about.

## Decision

Python only. Mux operations still shell out to ``tmux`` and ``cmux`` (those
are the actual mux interfaces), but everything else — state, parsing,
dispatch, tests — is python.

No bash glue scripts. No `lib/*.sh`. The `cmt` entry point in `bin/` is a
two-line shell stub that forwards to `python -m cmt.__main__`; nothing more.

## Why not Rust

The slow part of every operation is "wait for an LLM to finish a turn" or
"poll a jsonl file." Sub-millisecond startup matters less than legibility,
and the wire to the agent CLIs (tmux / cmux) is inherently shell-shaped.
A Rust rewrite of the same code paths would be ~3x the lines and slower
to iterate on.

## Why not stay in shell

Most of the per-agent logic — jsonl walking with structured event types,
codex's rollout-file discovery, agy's screen parser, the modal state
machines — is data-structure work. Shell can do it but reads as a
"sequence of commands hoping to compose into a state machine," not a
state machine. Python's dataclasses + small functions + pytest fit the
problem.

## Consequences

- **Test coverage is dense (146 unit tests as of writing).** Pytest +
  fixtures made it cheap to write — we have a real-tmux-server fixture and
  a fake-claude / fake-codex binary per test, exercised against the
  actual mux code paths.
- **No new runtime dependency at use time.** Users already have Python.
- **Python startup (~120ms) is the floor latency for every cmt command.**
  Acceptable for a workflow tool that mostly waits on LLM turns measured
  in seconds.
- **Spec → AgentSpec dataclass with callable fields, no class hierarchy.**
  Per-agent variation is three rows in the AGENTS table; that decision
  is downstream of "we have Python's dataclasses available."
