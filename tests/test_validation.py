#!/usr/bin/env python
#
"""Test structural validation of org content submitted by MCP clients."""

import pytest

from mcp_server.validation import (
    escape_headings_in_blocks,
    scan_headings,
    validate_journal_content,
    validate_project_entry,
    validate_project_section_content,
    validate_task_entry,
)


########################################################################
########################################################################
#
class TestScanHeadings:
    """Tests for heading detection in submitted org content."""

    ####################################################################
    #
    def test_finds_headings_with_levels_and_line_numbers(self):
        """
        GIVEN: org content with headings at several levels
        WHEN:  the content is scanned
        THEN:  each heading is reported with its level, text and line number
        """
        content = "** TODO Task A\n*** Description\nbody\n**** Detail"

        headings = scan_headings(content)

        assert [(h.level, h.text, h.line_number) for h in headings] == [
            (2, "TODO Task A", 1),
            (3, "Description", 2),
            (4, "Detail", 4),
        ]

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("*emphasis* at line start", id="emphasis"),
            pytest.param("*", id="bare-star"),
            pytest.param("  ** indented", id="indented"),
            pytest.param(
                "#+begin_src org\n* Tasks\n** TODO x\n#+end_src",
                id="inside-block",
            ),
        ],
    )
    def test_ignores_lines_that_are_not_authored_headings(self, content):
        """
        GIVEN: a line org would not treat as a heading, or literal text in a
               source block
        WHEN:  the content is scanned
        THEN:  nothing is reported

        Org needs stars at column zero followed by whitespace; block contents
        are literal text as far as the author is concerned.
        """
        assert scan_headings(content) == []


########################################################################
########################################################################
#
class TestEscapeHeadingsInBlocks:
    """Tests for comma-escaping literal org syntax inside blocks."""

    ####################################################################
    #
    def test_escapes_heading_lines_inside_a_block(self):
        """
        GIVEN: a block containing lines that org would read as headings
        WHEN:  the content is escaped
        THEN:  those lines gain a leading comma and are reported by line number
        """
        content = "#+begin_src org\n* Tasks\n** TODO x\n#+end_src\n"

        escaped, lines = escape_headings_in_blocks(content)

        assert escaped == "#+begin_src org\n,* Tasks\n,** TODO x\n#+end_src\n"
        assert lines == [2, 3]

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("** TODO Task\n*** Description\ntext\n", id="outside"),
            pytest.param(
                "#+begin_example\n,* Tasks\n#+end_example\n", id="pre-escaped"
            ),
        ],
    )
    def test_leaves_content_unchanged(self, content):
        """
        GIVEN: real headings outside any block, or already-escaped block text
        WHEN:  the content is escaped
        THEN:  it is returned untouched
        """
        assert escape_headings_in_blocks(content) == (content, [])

    ####################################################################
    #
    def test_only_the_matching_end_delimiter_closes_a_block(self):
        """
        GIVEN: a src block whose body mentions a different #+end_ delimiter
        WHEN:  the content is escaped
        THEN:  the block stays open until its own #+end_src
        """
        content = "#+begin_src org\n#+end_example\n* Tasks\n#+end_src\n"

        escaped, _ = escape_headings_in_blocks(content)

        assert ",* Tasks" in escaped


########################################################################
########################################################################
#
class TestValidateTaskEntry:
    """Tests for task entry structural validation."""

    ####################################################################
    #
    def test_accepts_a_well_formed_task(self):
        """
        GIVEN: a task with all subsections nested at level 3 or deeper
        WHEN:  it is validated
        THEN:  it is returned unchanged
        """
        entry = (
            "** TODO GH-1 Fix it\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: task-gh-1\n"
            ":END:\n"
            "*** Description\n"
            "Why.\n"
            "**** Detail\n"
            "More.\n"
        )

        assert validate_task_entry(entry) == entry

    ####################################################################
    #
    @pytest.mark.parametrize(
        "stray, expected",
        [
            pytest.param("** Notes", "*** Notes", id="sibling-task"),
            pytest.param("* Tasks", "*** Tasks", id="section-heading"),
        ],
    )
    def test_rejects_a_stray_shallow_heading(self, stray, expected):
        """
        GIVEN: a task entry whose fourth line is a ** or * heading
        WHEN:  it is validated
        THEN:  it is rejected, naming the line and the corrected form

        This is the silent-data-loss case: the parser keeps only the first
        level-2 heading, so everything after the stray heading would vanish
        while the write still reported success.
        """
        entry = f"** TODO Task A\n*** Description\nA.\n{stray}\nLost.\n"

        with pytest.raises(ValueError) as excinfo:
            validate_task_entry(entry)

        message = str(excinfo.value)
        assert "line 4" in message
        assert stray in message
        assert expected in message

    ####################################################################
    #
    @pytest.mark.parametrize(
        "entry, expected",
        [
            pytest.param(
                "* TODO Task A\n*** Description\n",
                "must begin with a level-2 heading",
                id="starts-too-shallow",
            ),
            pytest.param("just prose\n", "no heading", id="no-heading"),
            pytest.param(
                "** TODO Task\n*** Description\nA.\n  *** Indented\n",
                "indented",
                id="indented-heading",
            ),
        ],
    )
    def test_rejects_an_entry_that_is_not_a_task(self, entry, expected):
        """
        GIVEN: content that does not open with a level-2 heading, or whose
               headings do not start at column zero
        WHEN:  it is validated
        THEN:  it is rejected explaining what is wrong

        An indented heading is body text to org, so it and everything under it
        get absorbed into the preceding heading — the mechanism behind the
        2026-08-23 data loss.
        """
        with pytest.raises(ValueError, match=expected):
            validate_task_entry(entry)

    ####################################################################
    #
    def test_accepts_indented_single_star_bullets(self):
        """
        GIVEN: a task using indented '*' list bullets
        WHEN:  it is validated
        THEN:  it is accepted

        A lone indented '*' is an org list bullet, not a broken heading, so the
        indentation check must require two or more stars.
        """
        entry = "** TODO Task\n*** Notes\n- item\n  * sub bullet\n"

        assert validate_task_entry(entry) == entry

    ####################################################################
    #
    def test_escapes_org_samples_inside_blocks(self):
        """
        GIVEN: a task quoting org syntax inside a source block
        WHEN:  it is validated
        THEN:  the sample is comma-escaped rather than rejected

        Unescaped, that line would become a real heading on the next parse and
        hide every task after it.
        """
        entry = (
            "** TODO Task A\n*** Notes\n#+begin_src org\n* Tasks\n#+end_src\n"
        )

        assert ",* Tasks" in validate_task_entry(entry)


########################################################################
########################################################################
#
class TestValidateJournalContent:
    """Tests for journal entry body validation."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("- Did a thing\n- And another\n", id="bullets"),
            pytest.param("*** Sub topic\n- detail\n", id="deeper-heading"),
        ],
    )
    def test_accepts_valid_bodies(self, content):
        """
        GIVEN: an entry body of bullets, or one using *** subheadings
        WHEN:  it is validated
        THEN:  it is returned unchanged
        """
        assert validate_journal_content(content, "Headline") == content

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content, expected",
        [
            pytest.param(
                "- A thing\n** Extra topic\n",
                "separate journal entry",
                id="level-2",
            ),
            pytest.param("* Some heading\n", "date section", id="level-1"),
        ],
    )
    def test_rejects_shallow_headings_in_the_body(self, content, expected):
        """
        GIVEN: an entry body containing a ** or * heading
        WHEN:  it is validated
        THEN:  it is rejected, explaining how the entry would have been split
        """
        with pytest.raises(ValueError, match=expected):
            validate_journal_content(content, "Headline")

    ####################################################################
    #
    def test_rejects_a_multi_line_headline(self):
        """
        GIVEN: a headline containing a newline
        WHEN:  it is validated
        THEN:  it is rejected, since only the first line would survive
        """
        with pytest.raises(ValueError, match="single line"):
            validate_journal_content("- body", "Line one\nLine two")


########################################################################
########################################################################
#
class TestValidateProjectEntry:
    """Tests for project file structural validation."""

    ####################################################################
    #
    def test_accepts_a_well_formed_project(self):
        """
        GIVEN: a project file with one * heading and ** sections
        WHEN:  it is validated
        THEN:  it is returned unchanged
        """
        entry = "* Booklore  :project:\n** Description\nA thing.\n** Goals\n"

        assert validate_project_entry(entry) == entry

    ####################################################################
    #
    def test_rejects_a_second_level_one_heading(self):
        """
        GIVEN: a project entry containing two * headings
        WHEN:  it is validated
        THEN:  it is rejected, since only the first is ever read back
        """
        entry = "* Booklore\n** Description\nA.\n* Other Project\n** Notes\n"

        with pytest.raises(ValueError) as excinfo:
            validate_project_entry(entry)

        message = str(excinfo.value)
        assert "line 4" in message
        assert "** Other Project" in message

    ####################################################################
    #
    def test_rejects_an_entry_that_does_not_start_at_level_one(self):
        """
        GIVEN: a project entry whose first heading is at level 2
        WHEN:  it is validated
        THEN:  it is rejected explaining the level a project must start at
        """
        with pytest.raises(ValueError, match="must begin with a level-1"):
            validate_project_entry("** Booklore\n*** Description\n")


########################################################################
########################################################################
#
class TestValidateProjectSectionContent:
    """Tests for project section body validation."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("- [X] One\n- [ ] Two\n", id="bullets"),
            pytest.param("*** Sub topic\nDetail.\n", id="deeper-heading"),
        ],
    )
    def test_accepts_valid_bodies(self, content):
        """
        GIVEN: a section body of bullets, or one using *** subheadings
        WHEN:  it is validated
        THEN:  it is returned unchanged
        """
        assert validate_project_section_content("Goals", content) == content

    ####################################################################
    #
    def test_rejects_a_sibling_section_heading(self):
        """
        GIVEN: a section body containing a ** heading
        WHEN:  it is validated
        THEN:  it is rejected, naming the section it would have broken out of
        """
        with pytest.raises(ValueError, match="Goals"):
            validate_project_section_content("Goals", "- [ ] One\n** Notes\n")
