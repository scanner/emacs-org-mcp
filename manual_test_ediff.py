#!/usr/bin/env python3
"""
Manual test script for ediff approval workflow.

Usage:
    EMACS_EDIFF_APPROVAL=true python manual_test_ediff.py
"""

import logging
import os

from server import ensure_elisp_loaded, request_ediff_approval

# Set up logging to see error details
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


# Sample task content
OLD_TASK = """** TODO GH-127 Implement OAuth2 authentication
:PROPERTIES:
:ID:       C79031AC-94FE-4FDD-BBBF-7D3EE1A881E9
:CUSTOM_ID: task-gh-127
:CREATED:  <2025-01-09 Thu 10:30>
:MODIFIED: [2025-01-09 Thu 14:15]
:END:

*** Description

Implement OAuth2 authentication flow for user login.

*** Task items [1/3]
- [X] Create implementation plan
- [ ] Implement OAuth2 flow
- [ ] Run full test suite

*** Notes

Need to support Google and GitHub providers initially."""

NEW_TASK = """** TODO GH-127 Implement OAuth2 authentication
:PROPERTIES:
:ID:       C79031AC-94FE-4FDD-BBBF-7D3EE1A881E9
:CUSTOM_ID: task-gh-127
:CREATED:  <2025-01-09 Thu 10:30>
:MODIFIED: [2025-01-10 Fri 11:45]
:END:

*** Description

Implement OAuth2 authentication flow for user login.

*** Task items [2/3]
- [X] Create implementation plan
- [X] Implement OAuth2 flow with Google provider
- [ ] Run full test suite

*** Notes

Need to support Google and GitHub providers initially.

Google OAuth2 implementation complete. GitHub provider next."""


def main():
    """Run manual ediff approval test."""
    print("=" * 70)
    print("Manual Ediff Approval Test")
    print("=" * 70)
    print()

    # Check if ediff approval is enabled
    ediff_enabled = os.getenv("EMACS_EDIFF_APPROVAL", "").lower() in (
        "true",
        "1",
        "yes",
    )

    if not ediff_enabled:
        print("⚠️  EMACS_EDIFF_APPROVAL is not enabled!")
        print(
            "   Run with: EMACS_EDIFF_APPROVAL=true python manual_test_ediff.py"
        )
        print()
        print("Proceeding anyway (will auto-approve)...")
        print()
    else:
        print("📝 Ediff controls (in control buffer):")
        print("   C-c C-y  = Approve changes")
        print("   C-c C-k  = Reject changes")
        print("   q        = Quit (approves by default)")
        print("   You can edit buffer B before deciding")
        print()

    print("Testing task update approval workflow...")
    print()
    print("Context: gh-127 (OAuth2 authentication task)")
    print()

    # Force reload of elisp code (for development/testing)
    if ediff_enabled:
        print("Reloading emacs_ediff.el...")
        ensure_elisp_loaded(force=True)
        print()

    # Call the ediff approval function
    try:
        approved, final_content = request_ediff_approval(
            old_content=OLD_TASK,
            new_content=NEW_TASK,
            context_name="gh-127",
        )

        print()
        print("=" * 70)
        print("RESULT")
        print("=" * 70)
        print()
        print(f"Approved: {approved}")
        print()

        if approved:
            print("✅ User approved the changes")
            print()
            print("Final content:")
            print("-" * 70)
            print(final_content)
            print("-" * 70)

            # Check if content was edited
            if final_content != NEW_TASK:
                print()
                print("📝 Note: Content was edited during approval")
        else:
            print("❌ User rejected the changes")

        return 0 if approved else 1

    except Exception as e:
        print()
        print("=" * 70)
        print("ERROR")
        print("=" * 70)
        print()
        print(f"Exception occurred: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    main()
