"""
The one canonical format for ``:PROPERTIES:`` drawers.

Every drawer this server writes -- in tasks, projects, or anything else --
goes through :func:`format_drawer`, and every file it writes goes through
:func:`normalize_drawers`.  There is exactly one correct rendering of a given
set of properties, so a drawer that is already correct is left byte-identical
and produces no diff, no commit and no churn.

The format is Emacs's own.  ``org-property-format`` defaults to ``"%-10s %s"``:
the key (colons included) is padded to ten characters, then a single space,
then the value.  Keys of ten characters or more simply get their one space.
The drawer body is indented three spaces; ``:PROPERTIES:`` and ``:END:`` are
not indented.

::

    :PROPERTIES:
       :ID:       C5045326-9DC8-4F1E-A895-8895720DD928
       :CUSTOM_ID: project-asimap
       :CREATED:  <2026-04-03 Fri 23:13>
    :END:

Choosing Emacs's format matters beyond taste: it means ``org-set-property``
writes drawers we already consider canonical, so hand-editing a file in Emacs
does not reintroduce churn on the next write.
"""

# system imports
import re

# project imports
from mcp_server.validation import BLOCK_BEGIN_RE, BLOCK_END_RE

# =============================================================================
# Constants
# =============================================================================

# Indentation for property lines inside the drawer.  The :PROPERTIES: and
# :END: delimiters themselves stay at column zero.
DRAWER_INDENT = "   "

# Width the key is padded to, from Emacs's `org-property-format` ("%-10s %s").
# ":CUSTOM_ID:" is eleven characters and so overflows by one, exactly as Emacs
# renders it.
KEY_WIDTH = 10

# Order properties are written in.  Anything not listed follows, alphabetically,
# so unknown properties are still rendered deterministically.
PROPERTY_ORDER = (
    "ID",
    "CUSTOM_ID",
    "CREATED",
    "MODIFIED",
    "CLOSED",
    "PROJECT",
    "STATUS",
    "REPO",
)

DRAWER_START_RE = re.compile(r"^[ \t]*:PROPERTIES:[ \t]*$", re.IGNORECASE)
DRAWER_END_RE = re.compile(r"^[ \t]*:END:[ \t]*$", re.IGNORECASE)
PROPERTY_RE = re.compile(r"^[ \t]*:([^:\s]+):[ \t]*(.*?)[ \t]*$")


# =============================================================================
# Formatting
# =============================================================================


###############################################################################
#
def sort_properties(props: dict[str, str]) -> list[tuple[str, str]]:
    """
    Order properties canonically.

    Args:
        props: Mapping of property name (without colons) to value

    Returns:
        List of (name, value) pairs: known properties in ``PROPERTY_ORDER``,
        then everything else alphabetically.
    """
    known = [(name, props[name]) for name in PROPERTY_ORDER if name in props]
    extra = sorted(
        (name, value)
        for name, value in props.items()
        if name not in PROPERTY_ORDER
    )
    return known + extra


###############################################################################
#
def format_property(name: str, value: str) -> str:
    """
    Render a single property line in canonical form.

    Args:
        name: Property name without surrounding colons, e.g. ``CUSTOM_ID``
        value: The property's value

    Returns:
        The formatted line, without a trailing newline.
    """
    key = f":{name}:"
    return f"{DRAWER_INDENT}{key:<{KEY_WIDTH}} {value}".rstrip()


###############################################################################
#
def format_drawer(props: dict[str, str]) -> list[str]:
    """
    Render a complete ``:PROPERTIES:`` drawer in canonical form.

    Args:
        props: Mapping of property name (without colons) to value

    Returns:
        The drawer's lines, or an empty list when there are no properties.
        An empty drawer is omitted entirely rather than written out bare.
    """
    if not props:
        return []

    return [
        ":PROPERTIES:",
        *(
            format_property(name, value)
            for name, value in sort_properties(props)
        ),
        ":END:",
    ]


# =============================================================================
# Normalization
# =============================================================================


###############################################################################
#
def normalize_drawers(content: str) -> str:
    """
    Rewrite every ``:PROPERTIES:`` drawer in a file to canonical form.

    Args:
        content: Full text of an org file

    Returns:
        The text with all drawers canonically formatted.  Text that is already
        canonical is returned unchanged, so this is safe to run on every write.

    Note:
        Idempotent by construction: normalizing canonical output reproduces it
        exactly.  That is what keeps well-formed files from churning.

        Drawers inside ``#+begin_.../#+end_...`` blocks are left alone -- they
        are documentation samples, not real drawers, and rewriting them would
        corrupt the example the author wrote.

        A drawer with no ``:END:`` is left untouched rather than guessed at.
    """
    lines = content.split("\n")
    out: list[str] = []
    idx = 0
    open_block: str | None = None

    while idx < len(lines):
        line = lines[idx]

        # Track block delimiters so samples inside them stay verbatim.
        if open_block is None:
            if begin := BLOCK_BEGIN_RE.match(line):
                open_block = begin.group(1).lower()
                out.append(line)
                idx += 1
                continue
        else:
            end = BLOCK_END_RE.match(line)
            if end and end.group(1).lower() == open_block:
                open_block = None
            out.append(line)
            idx += 1
            continue

        if not DRAWER_START_RE.match(line):
            out.append(line)
            idx += 1
            continue

        # Collect the drawer body up to :END:.
        props: dict[str, str] = {}
        cursor = idx + 1
        closed = False
        while cursor < len(lines):
            if DRAWER_END_RE.match(lines[cursor]):
                closed = True
                break
            if match := PROPERTY_RE.match(lines[cursor]):
                props[match.group(1).upper()] = match.group(2)
            elif lines[cursor].strip():
                # Something that is not a property and not blank: this is not a
                # drawer we understand, so leave the whole thing alone.
                break
            cursor += 1

        if not closed:
            out.append(line)
            idx += 1
            continue

        out.extend(format_drawer(props) or [":PROPERTIES:", ":END:"])
        idx = cursor + 1

    return "\n".join(out)
