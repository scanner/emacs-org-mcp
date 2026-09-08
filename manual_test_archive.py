#!/usr/bin/env python3
"""
Manual test script for archiving a task through Emacs.

The unit tests replace the Emacs call with a fake that moves the heading in
Python, because that is the only way to exercise the code around it.  This
script is the other half: it runs the real ``org-archive-subtree`` in the
running Emacs, so what it proves is exactly what the fake cannot -- that the
elisp finds the heading, that org puts it where this expects, and that the
verification agrees with what actually happened.

Everything happens in a throwaway org directory, so the real tasks.org is
never touched.

Usage:
    uv run manual_test_archive.py
"""

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp_server.archiving import archive_tasks, format_archive_report
from mcp_server.config import Config, global_state
from mcp_server.utils import (
    ensure_elisp_loaded,
    get_emacsclient_path,
    quote_elisp,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TASKS_ORG = """* High Level Tasks (in order) [0/2]
- [ ] Keep working on the live one
- [ ] Something abandoned

* Tasks

** TODO GH-1 Keep working on the live one
:PROPERTIES:
   :CUSTOM_ID: task-gh-1
   :CREATED:  <2026-01-05 Mon 09:00>
:END:

*** Description

This task must still be here when the archive finishes.

** TODO GH-2 Something abandoned
:PROPERTIES:
   :CUSTOM_ID: task-gh-2
   :CREATED:  <2026-01-06 Tue 09:00>
:END:

*** Description

Work that was started and left behind.

*** Task items [0/2]
- [ ] never happened
- [ ] never will

* Completed Tasks

** DONE GH-0 Finished a while ago
:PROPERTIES:
   :CUSTOM_ID: task-gh-0
   :CREATED:  <2025-12-01 Mon 09:00>
   :CLOSED:   <2025-12-02 Tue 17:00>
:END:
"""


def main() -> int:
    """Archive a task out of a throwaway tasks.org using the real Emacs."""
    print("=" * 70)
    print("Manual Archive Test")
    print("=" * 70)
    print()

    if get_emacsclient_path() is None:
        print("emacsclient was not found, and archiving has no fallback.")
        print("Start the Emacs server (M-x server-start) and try again.")
        return 2

    # Reloaded every run, since the point of this script is to test whatever
    # the elisp says right now.
    print("Reloading emacs_archive.el...")
    if not ensure_elisp_loaded("emacs_archive.el", force=True):
        print("Could not load emacs_archive.el into Emacs.")
        return 2
    print()

    workspace = Path(tempfile.mkdtemp(prefix="emacs-org-mcp-archive-"))
    try:
        tasks_file = workspace / "tasks.org"
        tasks_file.write_text(TASKS_ORG, encoding="utf-8")

        # Only org_dir is given: everything else derives from it, so nothing
        # here can reach the real org directory.
        global_state.config = Config(
            org_dir=workspace,
            ediff_approval=False,
            git_autocommit=False,
        )

        print(f"Working in {workspace}")
        print("Archiving task-gh-2 ...")
        print()

        report = archive_tasks(["task-gh-2"])

        print("=" * 70)
        print("RESULT")
        print("=" * 70)
        print()
        print(format_archive_report(report))
        print()

        remaining = tasks_file.read_text(encoding="utf-8")
        print("-" * 70)
        print("tasks.org after")
        print("-" * 70)
        print(remaining)

        for result in report.archived:
            print("-" * 70)
            print(f"{result.archive_file} after")
            print("-" * 70)
            print(result.archive_file.read_text(encoding="utf-8"))

        if report.failure:
            print("The archive did not verify; see the report above.")
            return 1

        # What the fake in the unit tests cannot check: that org's own
        # archiving leaves the rest of the file alone.
        for expected in ("task-gh-1", "task-gh-0", "* Completed Tasks"):
            if expected not in remaining:
                print(f"MISSING from tasks.org after archiving: {expected}")
                return 1

        print("Archived, verified, and nothing else moved.")
        return 0

    finally:
        # Emacs is still visiting the files, so drop its buffers before the
        # directory goes away -- otherwise the next `find-file' on that path
        # is a buffer pointing at nothing.
        emacsclient = get_emacsclient_path()
        if emacsclient is not None:
            subprocess.run(
                [
                    emacsclient,
                    "--eval",
                    "(dolist (b (buffer-list))"
                    "  (when (and (buffer-file-name b)"
                    f"             (string-prefix-p {quote_elisp(str(workspace))}"
                    "                               (buffer-file-name b)))"
                    "    (kill-buffer b)))",
                ],
                capture_output=True,
                timeout=10,
            )
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
