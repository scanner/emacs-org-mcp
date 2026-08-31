#!/usr/bin/env python
#
r"""
Repair for orgmunge's drawer tokenizer.

Org is a line-oriented format: every construct is decided by the line it sits
on.  orgmunge's drawer pattern is not::

    r'^\s*:[^:]+:.+?:(?:end|END):'

Nothing in it stops at a line boundary, by two separate mechanisms.  The ``.+?``
spans newlines because the lexer compiles with ``re.DOTALL``.  The ``[^:]+``
spans them whatever the flags say, because a negated class matches ``\n``
unless ``\n`` is one of the characters it excludes -- so clearing DOTALL would
not have been enough on its own.

Any body line whose first non-blank character is a colon therefore opens a
drawer that runs to the next ``:END:`` *anywhere later in the file*, and every
heading in between is swallowed into a single opaque token.  A file with a
hundred property drawers always has a later ``:END:``, so the reach is
effectively unbounded.

This is the only token in orgmunge's lexer with unbounded newline reach.  The
others either exclude ``\n`` from their character classes (``t_SPACE``,
``t_METADATA``) or are built on ``\S``, which cannot match it (``t_TAGS``,
``t_TEXT``) -- so there is no point hunting for siblings of this bug.

That is how one fixed-width line in tasks.org made ``* Completed Tasks``
invisible: with the heading swallowed, every DONE task beneath it was reported
as active, and the first task below the lost heading was absorbed into the body
of the task above it.  The write path takes a task's extent from the same
mis-parse, so rewriting the last task in the Tasks section wrote over the
swallowed region and destroyed the heading.

The replacement is line-anchored, matching the convention
:mod:`mcp_server.properties` already uses for the same construct: a drawer
opens on a line that is *only* ``:NAME:``, runs over whole lines, and closes on
an ``:END:`` line.  It also cannot span a headline, which is org-element's rule
and the part that actually bounds the damage.

Patching a third-party library in place is only safe if it is verified, so
:func:`apply_drawer_fix` checks that orgmunge still ships the pattern we
believe is broken and raises if it does not.  A patch that silently stopped
applying would put us back to losing data.
"""

# system imports
import re

import ply.lex as lex
from orgmunge import Org
from orgmunge import lexer as orgmunge_lexer

# =============================================================================
# Constants
# =============================================================================

# The drawer pattern orgmunge 0.3.1 ships.  Verified at patch time so an
# upstream change cannot leave an ineffective patch in place unnoticed.
SHIPPED_DRAWER_PATTERN = r"^\s*:[^:]+:.+?:(?:end|END):"

# The line-oriented replacement.  Written with [^\n] rather than . because the
# lexer compiles with re.DOTALL, which would otherwise let both the body and
# the opening line run past their newline.
#
# The (?!\*+[ \t]) lookahead is what confines the token: it stops the body at
# the first headline, so an unterminated drawer can no longer consume the
# sections below it.  Anchoring the opening line alone is not enough -- a body
# line of exactly ":FOO:" still matches that, and without the lookahead the
# search continues across "* Completed Tasks" to reach a later ":END:".
FIXED_DRAWER_PATTERN = (
    r"^[ \t]*:[^:\s]+:[ \t]*\n"
    r"(?:(?!\*+[ \t])[^\n]*\n)*?"
    r"[ \t]*:(?:end|END):"
)

# Flags orgmunge builds its lexer with.  The rebuild has to use the same ones
# or every other token pattern changes meaning.
LEXER_FLAGS = re.DOTALL | re.MULTILINE


###############################################################################
#
class OrgmungePatchError(RuntimeError):
    """
    Raised when orgmunge does not look the way this patch expects.

    Note:
        Refusing to start beats parsing org files with a defect we believe we
        have fixed.
    """


# =============================================================================
# Patching
# =============================================================================

_applied = False


###############################################################################
#
def shipped_drawer_pattern() -> str:
    """
    Read the drawer pattern out of an unpatched orgmunge lexer.

    Returns:
        The regex PLY would use for the ``DRAWER`` token.

    Note:
        PLY takes a token's pattern from its function's docstring, which is
        where this reads it from.  Call before patching -- afterwards it
        returns the corrected pattern.
    """
    lexer = orgmunge_lexer.Lexer(Org.get_todos())
    return lexer.t_DRAWER.__doc__ or ""


###############################################################################
#
def apply_drawer_fix() -> None:
    """
    Make orgmunge tokenize drawers line by line. Idempotent.

    Raises:
        OrgmungePatchError: If orgmunge is not shipping the drawer pattern
            this patch was written against.  The file is safer unparsed than
            parsed by a lexer whose behaviour we can no longer predict.

    Note:
        orgmunge builds its token functions as closures inside
        ``Lexer.__init__``, so there is nothing importable to override.  The
        way in is to let the constructor run, correct the pattern on the
        instance, and rebuild.  That builds the lexer twice per parse, which
        is not free but is small next to parsing the file itself.
    """
    global _applied

    if _applied:
        return

    shipped = shipped_drawer_pattern()
    if shipped != SHIPPED_DRAWER_PATTERN:
        raise OrgmungePatchError(
            "orgmunge's DRAWER pattern is not the one this patch was written "
            f"against.\n\n  expected: {SHIPPED_DRAWER_PATTERN!r}\n"
            f"  found:    {shipped!r}\n\n"
            "orgmunge has changed. Re-check whether the drawer defect is "
            "still present (see mcp_server/orgmunge_patch.py) and update "
            "SHIPPED_DRAWER_PATTERN, or drop this patch if upstream fixed it."
        )

    original_init = orgmunge_lexer.Lexer.__init__

    def patched_init(self: orgmunge_lexer.Lexer, todos: dict) -> None:
        original_init(self, todos)
        self.t_DRAWER.__doc__ = FIXED_DRAWER_PATTERN
        self.lexer = lex.lex(module=self, reflags=LEXER_FLAGS)

    orgmunge_lexer.Lexer.__init__ = patched_init  # type: ignore[method-assign]
    _applied = True
