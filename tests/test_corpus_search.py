#!/usr/bin/env python
#
"""
Tests for searching loose org files and for searching every scope at once.

The fixture builds the file shapes an org directory accumulates, because each
breaks a different naive way of splitting a file into records: a file with no
headings, one that opens with text before its first heading, one that never
uses level one, one nested several levels deep, one whose source block holds a
heading-like line, and an `_archive` sibling.
"""

import re
from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.config import Config, parse_search_roots
from mcp_server.corpus import (
    format_org_search,
    owned_by_typed_corpus,
    resolve_scopes,
    scope_documents,
    search_org,
)
from mcp_server.files import (
    FilesCorpus,
    is_org_file,
    split_records,
    walk_org_files,
)
from tests.conftest import make_task, make_tasks_org

# A word that appears nowhere in any fixture but the one record meant to be
# found, so a hit for it is unambiguous.
NEEDLE = "quernstone"

# The six shapes, by the filename each is written to.
NO_HEADINGS = "scratch.org"
PREAMBLE = "2024.03.11-queue-migration-design.org"
DEEP = "handbook.org"
SINGLE = "chart-questions.org"
ARCHIVE = "tasks.org_archive"


########################################################################
#
@pytest.fixture
def loose_org_files(temp_org_dir: Path) -> Path:
    """An org directory holding every file shape the real one holds."""
    # No headings at all. The file is its own record or it is unreachable.
    (temp_org_dir / NO_HEADINGS).write_text(
        f"A stray note about {NEEDLE} with no heading above it.\n"
    )

    # Opens with text belonging to no heading, and never uses level one.
    (temp_org_dir / PREAMBLE).write_text(
        "This document serialises what a queue migration needs.\n"
        "\n"
        "** What defines a unique queue?\n"
        "A name, a schedule and a broker instance.\n"
        "\n"
        "*** Creating broker instances\n"
        "One per environment.\n"
    )

    # Five deep, with the content at the leaves and nothing but structure
    # above them.
    (temp_org_dir / DEEP).write_text(
        "* Engineering Handbook\n"
        "** Code Base\n"
        "*** Toolchain\n"
        "**** Fix the linker flags\n"
        "Rebuild against the vendored copy.\n"
        "***** Verification\n"
        "Run the unit tests.\n"
    )

    # One heading owning a long body, and a source block holding a line that
    # org itself would read as a heading.
    (temp_org_dir / SINGLE).write_text(
        "* Chart deploy questions\n"
        "Notes on the chart.\n"
        "\n"
        "#+begin_src org\n"
        "* Tasks\n"
        "** TODO not a real heading\n"
        "#+end_src\n"
        "\n"
        "The chart templates the queue name.\n"
    )

    # Org's archive convention: finished work beside the file it left.
    (temp_org_dir / ARCHIVE).write_text(
        "* DONE Build the widget\n"
        "** Description\n"
        f"The widget handles {NEEDLE} rendering.\n"
    )

    # Files that sit beside org files without being content.
    for junk in (
        "example.org.bak",
        "example.org~",
        "#example.org#",
        ".#example.org",
    ):
        (temp_org_dir / junk).write_text(f"* Junk\n{NEEDLE} should not match\n")

    return temp_org_dir


########################################################################
########################################################################
#
class TestFileSelection:
    """Tests for which files count as org content."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "name,wanted",
        [
            ("example.org", True),
            ("tasks.org_archive", True),
            ("20260825_archive", True),
            ("example.org.bak", False),
            ("example.org~", False),
            ("#example.org#", False),
            (".#example.org", False),
            ("notes.txt", False),
            (".hidden.org", False),
        ],
    )
    def test_org_content_is_taken_and_its_debris_is_not(self, name, wanted):
        """
        GIVEN: a filename from an org directory, which holds the server's own
               .bak files and Emacs's backup, lock and autosave files
               alongside real content
        WHEN:  it is considered for the corpus
        THEN:  .org files and <name>_archive siblings are content and
               everything else is not

        An archive has to survive a filter whose job is rejecting unusual
        extensions: it holds finished work, which is exactly the long-tail
        material a search across years is looking for.
        """
        assert is_org_file(name) is wanted

    ####################################################################
    #
    def test_a_walk_prunes_dot_directories_and_follows_no_symlinks(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a search root containing a dot-directory of org files and a
               symlink pointing back at the root
         WHEN: the root is walked
         THEN: neither is descended into, and every real file is found once

        A root holding a git repository would otherwise be read out of its
        object store, and a symlink to an ancestor would never terminate.
        """
        hidden = loose_org_files / ".git"
        hidden.mkdir()
        (hidden / "COMMIT_EDITMSG.org").write_text(f"* {NEEDLE}\nnope\n")
        (loose_org_files / "loop").symlink_to(loose_org_files)

        found = list(walk_org_files([loose_org_files]))
        names = [p.name for p in found]

        with check:
            assert "COMMIT_EDITMSG.org" not in names, "dot-directory descended"
        with check:
            assert len(names) == len(set(found)), "a file was yielded twice"
        with check:
            assert NO_HEADINGS in names and ARCHIVE in names

    ####################################################################
    #
    def test_a_root_given_twice_yields_each_file_once(
        self, loose_org_files: Path
    ):
        """
        GIVEN: the same directory named as a search root twice, or a root
               nested inside another
         WHEN: the roots are walked
         THEN: each file is yielded once

        A document appearing twice is ranked twice and shown twice.
        """
        once = list(walk_org_files([loose_org_files]))
        twice = list(walk_org_files([loose_org_files, loose_org_files]))

        assert len(once) == len(twice)

    ####################################################################
    #
    def test_a_file_too_large_to_be_notes_is_skipped(
        self, loose_org_files: Path, mocker
    ):
        """
        GIVEN: an org file larger than the corpus will read
         WHEN: the corpus is built
         THEN: it is left out, and the other files are still searched

        This bounds what a mistyped search root can cost. The limit is
        mocked low here so the fixture need not actually be megabytes.
        """
        mocker.patch("mcp_server.files.MAX_FILE_BYTES", 200)
        (loose_org_files / "huge.org").write_text(
            f"* Huge\n{NEEDLE} " + ("padding " * 100)
        )

        paths = {r.path.name for r in FilesCorpus().records()}

        with check:
            assert "huge.org" not in paths
        with check:
            assert NO_HEADINGS in paths, "other files still read"

    ####################################################################
    #
    def test_a_file_that_is_not_text_is_skipped_rather_than_mangled(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file named .org whose bytes are not valid UTF-8
         WHEN: the corpus is built
         THEN: it is left out rather than decoded with replacement characters

        It is an org file by extension only, and indexing its bytes would put
        noise into the ranking for every other search.
        """
        (loose_org_files / "binary.org").write_bytes(b"* Heading\n\xff\xfe\x00")

        paths = {r.path.name for r in FilesCorpus().records()}

        assert "binary.org" not in paths


########################################################################
########################################################################
#
class TestRecordSplitting:
    """Tests for turning one org file into the records a search returns."""

    ####################################################################
    #
    def test_a_heading_owns_its_own_text_and_not_its_children(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file nested five levels deep, where the text sits at the
               leaves and the headings above hold nothing but more headings
         WHEN: it is split into records
         THEN: each record is one heading and the text directly under it, and
               a heading holding no text of its own is not a record

        A record covering its whole subtree would count every deep term again
        in each of its ancestors, and ranking would put the outermost heading
        above the one that answers the query. The ancestors are still readable
        on the result line, as the path the record came from.
        """
        path = loose_org_files / DEEP
        records = split_records(path.read_text(), path)

        by_headline = {r.headline: r for r in records}

        with check:
            assert set(by_headline) == {
                "Fix the linker flags",
                "Verification",
            }, "only the headings carrying text are records"
        with check:
            assert (
                "Run the unit tests"
                not in by_headline["Fix the linker flags"].content
            ), "a child's text must not be counted in its parent"
        with check:
            assert by_headline["Verification"].heading_path == [
                "Engineering Handbook",
                "Code Base",
                "Toolchain",
                "Fix the linker flags",
            ], "the structural headings survive as the path"

    ####################################################################
    #
    def test_text_above_the_first_heading_is_not_lost(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file that opens with text before any heading, and whose
               headings start at level two rather than level one
         WHEN: it is split into records
         THEN: the opening text is a record of its own, named for the file,
               and the level-two headings are ordinary records

        A file need not start at level one and need not descend one level at
        a time, so a parent is found by level rather than by being the
        previous heading.
        """
        path = loose_org_files / PREAMBLE
        records = split_records(path.read_text(), path)

        first = records[0]
        deepest = records[-1]

        with check:
            assert first.headline == PREAMBLE, "named for the file"
        with check:
            assert first.level == 0
        with check:
            assert "serialises what a queue migration needs" in first.content
        with check:
            assert deepest.heading_path == ["What defines a unique queue?"], (
                "the level-two heading is the level-three heading's parent"
            )

    ####################################################################
    #
    def test_a_file_with_no_headings_is_still_findable(
        self, loose_org_files: Path
    ):
        """
        GIVEN: an org file containing text and no headings at all
         WHEN: it is split into records
         THEN: the file itself is one record, so its content is searchable
        """
        path = loose_org_files / NO_HEADINGS
        records = split_records(path.read_text(), path)

        with check:
            assert len(records) == 1
        with check:
            assert NEEDLE in records[0].content

    ####################################################################
    #
    def test_a_heading_inside_a_source_block_does_not_split_a_record(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file whose source block contains a line org itself would read
               as a heading
         WHEN: it is split into records
         THEN: the block is part of the record it sits in, and the sample
               headings inside it do not become records

        On write this server comma-escapes such lines, because org gets this
        wrong and splits the file. On read the author's meaning is what a
        search should return -- and a file this server did not write may never
        have been through that repair.
        """
        path = loose_org_files / SINGLE
        records = split_records(path.read_text(), path)

        headlines = [r.headline for r in records]

        with check:
            assert headlines == ["Chart deploy questions"]
        with check:
            assert (
                "The chart templates the queue name." in records[0].content
            ), "text after the block belongs to the same record"

    ####################################################################
    #
    def test_a_records_link_points_at_its_own_heading(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file whose headings repeat a generic name, as an archive of
               many tasks repeats Description
         WHEN: each record's link is read
         THEN: it names the line the heading sits on, so it opens that record
               rather than the first heading sharing its name

        Org's `::*Heading` search finds the first match in the file, which
        for a repeated subsection name is the wrong one.
        """
        path = loose_org_files / "repeated.org"
        path.write_text(
            "* First task\n"
            "** Description\n"
            "The first body.\n"
            "* Second task\n"
            "** Description\n"
            "The second body.\n"
        )

        records = split_records(path.read_text(), path)
        lines = [r.line for r in records]

        with check:
            assert lines == [2, 5], f"heading lines, got {lines}"
        with check:
            assert records[0].ref != records[1].ref, (
                "two Description headings must not share a link"
            )
        with check:
            assert records[1].ref.endswith("::5")

    ####################################################################
    #
    def test_an_archived_record_says_so(self, loose_org_files: Path):
        """
        GIVEN: a record from an org <name>_archive file
         WHEN: it is rendered as a result
         THEN: it is marked archived, and its link names the file and heading

        Archived work is finished or abandoned, which changes how a hit
        should be read: it describes what was done, not what the code does
        now.
        """
        hits = search_org(NEEDLE, scope=["files"]).hits
        archived = [h for h in hits if h.doc.payload.is_archive]

        with check:
            assert archived, "the archive should be searchable"
        with check:
            assert "[archived]" in format_org_search(
                search_org(NEEDLE, scope=["files"]), detail="index"
            )
        with check:
            assert re.fullmatch(
                rf"file:\S*{ARCHIVE}::\d+", archived[0].doc.ref
            ), (
                f"ref should be a line-anchored org link, got {archived[0].doc.ref}"
            )
        with check:
            assert archived[0].doc.ref in format_org_search(
                search_org(NEEDLE, scope=["files"]), detail="index"
            ), (
                "the link has to reach the caller, not merely exist on the record"
            )


########################################################################
########################################################################
#
class TestScopeOwnership:
    """Tests for which scope owns which file."""

    ####################################################################
    #
    def test_a_typed_file_is_searched_under_its_own_scope_only(
        self, loose_org_files: Path, sample_journal_files, sample_project_files
    ):
        """
        GIVEN: an org directory holding tasks.org, dated journal files,
               project files, and loose org files beside them
         WHEN: every scope is searched together
         THEN: each file is searched once, under the scope that owns it, and
               the loose files are the only ones the files scope reads

        A document ranked twice is shown twice, and the same file set has to
        come back from the files scope whatever it was asked for alongside.
        """
        (loose_org_files / "tasks.org").write_text(
            make_tasks_org(
                [make_task(headline="A task", custom_id="task-a")], []
            )
        )

        owned = FilesCorpus(skip=owned_by_typed_corpus).records()
        names = {r.path.name for r in owned}

        with check:
            assert "tasks.org" not in names, "owned by the tasks scope"
        with check:
            assert not any(n.startswith("20") and n.isdigit() for n in names), (
                "dated journal files are owned by the journal scope"
            )
        with check:
            assert ARCHIVE in names, (
                "an archive sits beside tasks.org and no typed tool reads it"
            )

    ####################################################################
    #
    def test_the_generated_project_index_is_not_searched(
        self, loose_org_files: Path, sample_project_files
    ):
        """
        GIVEN: a projects directory holding the generated index.org
         WHEN: the files scope is built
         THEN: the index is left out

        It is derived from the project files, so a hit in it returns a table
        of contents where the project itself is the answer.
        """
        index = loose_org_files / "projects" / "index.org"
        index.write_text(f"* Project index\n- {NEEDLE}\n")

        assert owned_by_typed_corpus(index) is True

    ####################################################################
    #
    @pytest.mark.parametrize(
        "asked,expected",
        [
            (None, ["tasks", "journal", "projects", "files"]),
            ([], ["tasks", "journal", "projects", "files"]),
            (["files"], ["files"]),
            (["FILES", "files"], ["files"]),
            (["files", "tasks"], ["tasks", "files"]),
        ],
    )
    def test_scopes_resolve_to_a_stable_de_duplicated_order(
        self, asked, expected
    ):
        """
        GIVEN: a scope selection, possibly empty, repeated or differently cased
         WHEN: it is resolved
         THEN: it becomes the named scopes once each, in a fixed order, and
               naming nothing means all of them
        """
        assert resolve_scopes(asked) == expected

    ####################################################################
    #
    def test_an_unknown_scope_is_refused_by_name(self):
        """
        GIVEN: a scope that does not exist
         WHEN: a search is run with it
         THEN: it is refused with a message naming it and listing the real ones
        """
        with pytest.raises(ValueError, match="notes"):
            resolve_scopes(["notes"])


########################################################################
########################################################################
#
class TestCrossScopeSearch:
    """Tests for searching every corpus as one."""

    ####################################################################
    #
    def test_results_from_every_scope_rank_together_and_say_which(
        self,
        loose_org_files: Path,
        sample_journal_files,
        sample_project_files,
    ):
        """
        GIVEN: the same distinctive word written in a task, a journal entry
               and a loose org file
         WHEN: every scope is searched at once
         THEN: all three come back in one ranked set, each line naming the
               scope it came from

        The scopes have different follow-up calls, so a mixed result set is
        unusable without saying which is which. Ranking them together rather
        than merging separate searches is the point: IDF is a property of the
        corpus being searched, so scoring each scope apart makes the same term
        worth different amounts in one result set.
        """
        (loose_org_files / "tasks.org").write_text(
            make_tasks_org(
                [
                    make_task(
                        headline=f"Investigate {NEEDLE}", custom_id="task-q"
                    )
                ],
                [],
            )
        )
        journal = loose_org_files / "journal" / "20260831"
        journal.write_text(f"* 2026-08-31\n\n** 09:00 Notes\n- saw {NEEDLE}\n")

        output = format_org_search(search_org(NEEDLE), detail="index")

        for label in ("task:", "journal:", "file:"):
            with check:
                assert label in output, f"{label} missing from:\n{output}"

    ####################################################################
    #
    def test_a_scope_that_does_not_exist_is_empty_rather_than_an_error(
        self, tmp_path: Path, config_factory
    ):
        """
        GIVEN: an org directory with no tasks.org, no journal directory and no
               projects directory -- only loose org files
         WHEN: every scope is searched
         THEN: the loose files are searched and the absent scopes contribute
               nothing

        This is the installation the files scope exists for. Generic search
        has to work without adopting any of this server's conventions.
        """
        config_factory(
            Config(org_dir=tmp_path, ediff_approval=False, git_autocommit=False)
        )
        (tmp_path / "loose.org").write_text(f"* A note\nAbout {NEEDLE}.\n")

        results = search_org(NEEDLE)

        with check:
            assert len(results.hits) == 1
        with check:
            assert results.hits[0].doc.payload.headline == "A note"
        for scope in ("tasks", "journal", "projects"):
            with check:
                assert scope_documents(scope, False) == [], (
                    f"{scope} should be empty, not raise"
                )

    ####################################################################
    #
    def test_the_filename_is_searchable_alongside_the_headings(
        self, loose_org_files: Path
    ):
        """
        GIVEN: a file named for its subject whose headings never say it
         WHEN: that subject is searched for
         THEN: the file's records are found

        A dated design document is named for what it is about and its
        headings are about the parts. Without the name in the index, searching
        the subject finds the file only by accident.
        """
        hits = search_org("queue migration design", scope=["files"]).hits

        assert any(h.doc.payload.path.name == PREAMBLE for h in hits)


########################################################################
########################################################################
#
class TestSearchRootConfiguration:
    """Tests for where the loose files are looked for."""

    ####################################################################
    #
    def test_roots_follow_org_dir_unless_they_are_named(self, tmp_path: Path):
        """
        GIVEN: a Config built with an org directory and nothing else
         WHEN: its search roots are read
         THEN: they are that org directory

        A default naming the real org directory would make a Config built for
        a temporary one read the user's own files -- which is how this server
        once wrote to live data during a test run.
        """
        elsewhere = tmp_path / "elsewhere"

        with check:
            assert Config(org_dir=tmp_path).search_roots == [tmp_path]
        with check:
            assert Config(
                org_dir=tmp_path, search_roots=[elsewhere]
            ).search_roots == [elsewhere]

    ####################################################################
    #
    def test_several_roots_are_read_from_one_environment_variable(self):
        """
        GIVEN: SEARCH_ROOTS naming more than one directory, separated the way
               PATH is on this platform
         WHEN: it is parsed
         THEN: each becomes a root, with ~ expanded, and an empty setting
               names none so that org_dir is used
        """
        import os

        raw = os.pathsep.join(["~/org", "/srv/notes", ""])

        with check:
            assert parse_search_roots(raw) == [
                Path.home() / "org",
                Path("/srv/notes"),
            ]
        with check:
            assert parse_search_roots("") == []
