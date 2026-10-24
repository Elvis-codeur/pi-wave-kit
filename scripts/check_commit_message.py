#!/usr/bin/env python3
"""Mechanically-checkable half of CONTRIBUTING.md's commit-message protocol. Installed as a
`pre-commit` commit-msg hook (see .pre-commit-config.yaml) -- this is NOT a full style-ok/style-bad
judgment call, just the parts a script can actually verify without guessing at meaning:

- the subject line (first line) is not empty
- the subject line is <= 72 characters (the git/GitHub convention; keeps `git log --oneline` and
  the GitHub commit list readable)
- the subject line does not end with a period (imperative-mood convention: a subject is a
  heading, not a sentence)
- if there's a body, the second line is blank (git's own convention for where the subject ends)

Usage (what pre-commit's commit-msg hook calls it as): check_commit_message.py <path-to-COMMIT_EDITMSG>
"""

from __future__ import annotations

import sys


def check(message: str) -> list[str]:
    lines = message.splitlines()
    # Strip comment lines (git leaves "# ..." lines in COMMIT_EDITMSG for the editor view).
    lines = [ln for ln in lines if not ln.startswith("#")]
    while lines and not lines[0].strip():
        lines.pop(0)

    problems = []
    if not lines or not lines[0].strip():
        problems.append("commit message has no subject line")
        return problems

    subject = lines[0]
    if len(subject) > 72:
        problems.append(f"subject line is {len(subject)} chars, keep it <= 72: {subject!r}")
    if subject.rstrip().endswith("."):
        problems.append("subject line should not end with a period (it's a heading, not a sentence)")
    if len(lines) > 1 and lines[1].strip():
        problems.append("line 2 must be blank (separates the subject from the body)")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_commit_message.py <commit-message-file>", file=sys.stderr)
        return 2
    message = open(argv[1], encoding="utf-8").read()
    problems = check(message)
    if problems:
        print("commit message does not follow CONTRIBUTING.md's format:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
