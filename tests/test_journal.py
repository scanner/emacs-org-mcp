#!/usr/bin/env python
#
"""
Tests for the day-by-day journal: which file a date names, and what an entry
promises once it is in one.

The journal is the corpus most often written by hand, so the promises here
lean towards reading what is already there rather than imposing a shape on
it -- either filename convention is honoured, a day with no file is not an
error, and an edit leaves the rest of the day exactly as it was.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
from pytest_check import check

from mcp_server.journal import (
    create_journal_entry,
    find_journal_entry,
    get_journal_path,
    parse_journal_entries,
    search_journal,
    update_journal_entry,
)
from tests.conftest import (
    JournalFilesInfo,
    make_journal_entry,
    make_journal_file,
)


class TestGetJournalPath:
    """
    Which file a date names.

    A journal directory is written by hand as much as by this server, and the
    files in one are named either `20250915` or `20250915.org` depending on
    who started it. Both are read, and a new file joins whichever convention
    the directory already keeps rather than imposing one.
    """

    def test_a_date_names_a_file_in_the_journal_directory(
        self, empty_journal_dir: Path
    ):
        """
        GIVEN: A date with no journal file yet
         WHEN: Its path is worked out
         THEN: It is that date as YYYYMMDD, inside the journal directory, so
               the files sort chronologically by name
        """
        path = get_journal_path(date(2025, 1, 15))

        with check:
            assert path.name == "20250115"
        with check:
            assert path.parent == empty_journal_dir

    def test_an_existing_file_is_found_whichever_way_it_is_named(
        self, empty_journal_dir: Path
    ):
        """
        GIVEN: A day whose file was written with a .org extension, and a day
               whose file exists under both spellings
         WHEN: Each date's path is worked out
         THEN: The existing file is returned rather than a new name beside it
          AND: Where both exist the .org one wins, so the pair is resolved the
               same way every time instead of by directory order
        """
        org_only = empty_journal_dir / "20250615.org"
        org_only.write_text("* 2025-06-15\n")

        both_plain = empty_journal_dir / "20250720"
        both_org = empty_journal_dir / "20250720.org"
        both_plain.write_text("* 2025-07-20\n")
        both_org.write_text("* 2025-07-20\n")

        with check:
            assert get_journal_path(date(2025, 6, 15)) == org_only
        with check:
            assert get_journal_path(date(2025, 7, 20)) == both_org

    @pytest.mark.parametrize(
        "suffix", [".org", ""], ids=["org-extension", "no-extension"]
    )
    def test_a_new_file_is_named_the_way_the_existing_ones_are(
        self, empty_journal_dir: Path, suffix: str
    ):
        """
        GIVEN: A journal directory whose files all follow one naming
               convention
         WHEN: A path is worked out for a day that has no file yet
         THEN: The new name follows that convention, so a directory does not
               end up half in one spelling and half in the other
        """
        (empty_journal_dir / f"20250101{suffix}").write_text("* 2025-01-01\n")

        path = get_journal_path(date(2025, 9, 15))

        assert path.name == f"20250915{suffix}"


class TestParseJournalEntries:
    """Reading a day's entries back out of its file."""

    def test_an_entry_comes_back_whole(
        self, sample_journal_files: JournalFilesInfo
    ):
        """
        GIVEN: A journal file holding a day's entries, one of them tagged
         WHEN: The file is parsed
         THEN: Every entry is found, each carrying the time it was written,
               its headline and its tags -- these are what an entry is looked
               up and filtered by, so an entry parsed without them is found
               by nothing
        """
        entries = parse_journal_entries(sample_journal_files["today_file"])

        with check:
            assert len(entries) == sample_journal_files["today_entry_count"]
        with check:
            assert entries[0].time == "09:00"
        with check:
            assert "JIRA-1234" in entries[0].headline
        with check:
            assert entries[0].file_date == sample_journal_files[
                "today"
            ].strftime("%Y%m%d")
        with check:
            assert len([e for e in entries if "daily_summary" in e.tags]) == 1

    def test_the_day_an_entry_belongs_to_ignores_the_file_extension(
        self, empty_journal_dir: Path
    ):
        """
        GIVEN: A journal file named with a .org extension
         WHEN: Its entries are parsed
         THEN: Each reports its day as YYYYMMDD with no extension, since that
               is the date, not the filename -- carrying ".org" into it would
               make the same day compare unequal to itself depending on which
               spelling the file happened to use
        """
        journal_file = empty_journal_dir / "20250810.org"
        journal_file.write_text(
            "* 2025-08-10\n\n** 14:30 JIRA-1234 An entry\n- Did something\n"
        )

        (entry,) = parse_journal_entries(journal_file)

        assert entry.file_date == "20250810"

    def test_a_day_with_no_file_has_no_entries(self, empty_journal_dir: Path):
        """
        GIVEN: A date nobody has written anything for
         WHEN: Its file is parsed
         THEN: It reads as no entries rather than failing, because most days
               have no journal file until the first entry is written
        """
        assert parse_journal_entries(empty_journal_dir / "19700101") == []


class TestCreateJournalEntry:
    """Writing a new entry into a day."""

    def test_the_first_entry_of_a_day_starts_the_file(
        self, empty_journal_dir: Path
    ):
        """
        GIVEN: A day with no journal file yet
         WHEN: An entry is written for it, with tags
         THEN: The file is created under that date's own heading, and the
               entry reads back with its time, headline and tags intact

        The date heading is what makes the file an org document rather than a
        list of loose entries, and it is written once -- when the day's first
        entry is.
        """
        target_date = date(2025, 3, 15)

        returned_date, entry = create_journal_entry(
            target_date=target_date,
            time_str="10:00",
            headline="First entry of the day",
            content="- Did something",
            tags=["daily_summary"],
        )

        journal_file = empty_journal_dir / "20250315"
        (written,) = parse_journal_entries(journal_file)

        with check:
            assert returned_date == target_date
        with check:
            assert journal_file.read_text().startswith("* 2025-03-15")
        with check:
            assert (entry.time, entry.headline) == (
                "10:00",
                "First entry of the day",
            )
        with check:
            assert (written.time, written.headline) == (
                "10:00",
                "First entry of the day",
            )
        with check:
            assert "daily_summary" in written.tags

    def test_a_later_entry_joins_the_day_already_started(
        self, sample_journal_files: JournalFilesInfo
    ):
        """
        GIVEN: A day that already has entries
         WHEN: Another is written
         THEN: It is added after them and the earlier ones are still there,
               since a journal is appended to through the day and rewriting
               the file must not cost the morning's entries
        """
        before = parse_journal_entries(sample_journal_files["today_file"])

        create_journal_entry(
            target_date=sample_journal_files["today"],
            time_str="20:00",
            headline="Evening update",
            content="- Late night work",
        )

        entries = parse_journal_entries(sample_journal_files["today_file"])

        with check:
            assert len(entries) == len(before) + 1
        with check:
            assert entries[-1].time == "20:00"
        with check:
            assert [e.headline for e in entries[:-1]] == [
                e.headline for e in before
            ]


class TestFindJournalEntry:
    """Tests for find_journal_entry function."""

    @pytest.fixture()
    def multi_entry_file(self, empty_journal_dir: Path) -> Path:
        """Journal file with unique and duplicate-time entries for lookup tests."""
        journal_file = empty_journal_dir / "20250810"
        journal_file.write_text(
            "* 2025-08-10\n\n"
            "** 09:00 Morning standup\n"
            "- Discussed priorities\n\n"
            "** 14:30 First afternoon task\n"
            "- Content A\n\n"
            "** 14:30 Second afternoon task\n"
            "- Content B\n"
        )
        return journal_file

    @pytest.mark.parametrize(
        "time_str, headline, expected_in_headline",
        [
            ("09:00", None, "Morning standup"),
            ("14:30", "Second", "Second afternoon task"),
        ],
    )
    def test_an_entry_is_named_by_its_time_and_if_need_be_its_headline(
        self,
        multi_entry_file: Path,
        time_str: str,
        headline: str | None,
        expected_in_headline: str,
    ):
        """
        GIVEN: A day holding one entry at a unique time and two that share a
               time
         WHEN: An entry is looked up by time, and by time plus headline where
               the time alone is not enough
         THEN: The intended entry comes back either way, so a caller only has
               to give the headline when the time does not settle it
        """
        entry = find_journal_entry(multi_entry_file, time_str, headline)
        assert expected_in_headline in entry.headline

    @pytest.mark.parametrize(
        "time_str, message",
        [
            pytest.param("23:59", "No journal entry found", id="no-entry"),
            pytest.param("14:30", "Multiple entries", id="two-entries"),
        ],
    )
    def test_a_time_that_does_not_name_one_entry_is_refused(
        self, multi_entry_file: Path, time_str: str, message: str
    ):
        """
        GIVEN: A time matching no entry, or a time two entries share
         WHEN: An entry is looked up by it alone
         THEN: It is refused, saying which of the two happened -- returning
               the first of several would edit whichever entry happened to be
               written first
        """
        with pytest.raises(ValueError, match=message):
            find_journal_entry(multi_entry_file, time_str)


class TestUpdateJournalEntry:
    """Tests for update_journal_entry function."""

    def test_an_update_replaces_what_it_was_given(
        self, sample_journal_files: JournalFilesInfo
    ):
        """
        GIVEN: An existing entry
         WHEN: It is updated with a new headline, new content and new tags
         THEN: All three are in the file afterwards, and the entry returned
               describes the change -- what it was and what it now is

        The three are set in one call because that is how an edit arrives:
        someone rewrites the entry. Setting one and silently reverting
        another is the failure, and testing them apart cannot see it.
        """
        entries = parse_journal_entries(sample_journal_files["today_file"])
        original = entries[0]

        old_entry, new_entry, _ = update_journal_entry(
            file_path=sample_journal_files["today_file"],
            time_str=original.time,
            headline="Updated headline",
            content="- New bullet point",
            tags=["new_tag", "another_tag"],
        )

        written = parse_journal_entries(sample_journal_files["today_file"])[0]

        with check:
            assert old_entry.headline == original.headline
        with check:
            assert new_entry.headline == "Updated headline"
        with check:
            assert written.headline == "Updated headline"
        with check:
            assert "New bullet point" in written.content
        with check:
            assert {"new_tag", "another_tag"} <= set(written.tags)

    def test_updating_one_entry_leaves_the_rest_of_the_day_alone(
        self, sample_journal_files: JournalFilesInfo
    ):
        """
        GIVEN: A day holding several entries
         WHEN: One of them is updated
         THEN: The others are unchanged and none has gone -- the whole file
               is rewritten to change one entry, so every other entry in it
               is at risk on every edit
        """
        original_entries = parse_journal_entries(
            sample_journal_files["today_file"]
        )
        original_count = len(original_entries)
        first_entry = original_entries[0]
        second_entry = original_entries[1]

        update_journal_entry(
            file_path=sample_journal_files["today_file"],
            time_str=first_entry.time,
            headline="Modified first entry",
            content="- Modified content",
        )

        updated_entries = parse_journal_entries(
            sample_journal_files["today_file"]
        )

        # Same number of entries
        assert len(updated_entries) == original_count

        # Second entry unchanged
        assert updated_entries[1].headline == second_entry.headline
        assert updated_entries[1].time == second_entry.time

    def test_update_preserves_blank_line_separators(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """
        GIVEN: A day whose entries are separated by blank lines, as org
               documents are written
         WHEN: One entry is updated
         THEN: The blank line before the next entry is still there, so an
               edit does not slowly compact the file into an unreadable block

        Rendering an entry strips its trailing whitespace while the range
        being replaced includes the blank line after it, so the separator is
        what the splice eats.
        """
        original_entries = parse_journal_entries(
            sample_journal_files["today_file"]
        )
        first_entry = original_entries[0]
        second_entry = original_entries[1]

        update_journal_entry(
            file_path=sample_journal_files["today_file"],
            time_str=first_entry.time,
            headline="Updated first entry",
            content="- New content",
        )

        updated_content = sample_journal_files["today_file"].read_text()

        # The second entry should still be preceded by a blank line.
        # Use to_org() to get the exact heading line (including tags).
        second_heading_line = second_entry.to_org().split("\n")[0]
        assert f"\n\n{second_heading_line}" in updated_content, (
            "Blank line separator before second entry was lost after update.\n"
            f"Looking for blank line before: {second_heading_line}\n"
            f"File content:\n{updated_content}"
        )

    @pytest.mark.parametrize("filename", ["20250810.org", "20250810"])
    def test_an_updated_entry_reports_its_day_without_the_extension(
        self, empty_journal_dir: Path, filename: str
    ):
        """
        GIVEN: A journal file named with or without the .org extension
         WHEN: An entry in it is updated
         THEN: The entry returned reports its day as YYYYMMDD either way,
               since a caller uses that to address the day again and ".org"
               is not part of the date
        """
        journal_file = empty_journal_dir / filename
        journal_file.write_text(
            "* 2025-08-10\n\n** 14:30 Original headline\n- Original content\n"
        )

        _, new_entry, _ = update_journal_entry(
            file_path=journal_file,
            time_str="14:30",
            headline="Updated headline",
            content="- Updated content",
        )

        assert new_entry.file_date == "20250810", (
            f"Expected file_date='20250810', got '{new_entry.file_date}'"
        )

    @pytest.mark.parametrize(
        "existing_time, existing_headline, new_time, new_headline, expected_headlines",
        [
            # Change time on a unique entry (09:00 is unique in the file)
            (
                "09:00",
                None,
                "09:30",
                "Morning updated",
                ["09:30 Morning updated", "First task", "Second task"],
            ),
            # Disambiguate by headline when two entries share a time
            (
                None,
                "Second task",
                "14:30",
                "Second task updated",
                ["Morning standup", "First task", "Second task updated"],
            ),
        ],
        ids=["change-time", "disambiguate-by-headline"],
    )
    def test_an_entry_can_be_found_by_one_time_and_given_another(
        self,
        empty_journal_dir: Path,
        existing_time: str | None,
        existing_headline: str | None,
        new_time: str,
        new_headline: str,
        expected_headlines: list[str],
    ):
        """
        GIVEN: A day holding an entry at a unique time and two that share one
         WHEN: An entry is updated, named by its current time or by its
               headline, and given a different time
         THEN: The intended entry changes and its neighbours do not

        The entry is addressed by what it is now and rewritten to what it
        should be, so the two must not be confused: looking the entry up by
        its new time would find nothing, or worse, find someone else's.
        """
        journal_file = empty_journal_dir / "20250810"
        journal_file.write_text(
            "* 2025-08-10\n\n"
            "** 09:00 Morning standup\n"
            "- Discussed priorities\n\n"
            "** 14:30 First task\n"
            "- Content A\n\n"
            "** 14:30 Second task\n"
            "- Content B\n"
        )

        update_journal_entry(
            file_path=journal_file,
            time_str=new_time,
            headline=new_headline,
            content="- Updated content",
            existing_time=existing_time,
            existing_headline=existing_headline,
        )

        updated_entries = parse_journal_entries(journal_file)
        for entry, expected in zip(
            updated_entries, expected_headlines, strict=False
        ):
            assert expected in f"{entry.time} {entry.headline}"


class TestSearchJournal:
    """
    Tests for searching journal entries.

    Search returns ranked results rather than a filtered list, so a hit
    carries its entry as a payload alongside its score and how much of the
    query it covered. The guarantees below are the ones the substring search
    made and that ranking must keep -- finding an entry by its headline or its
    body, ignoring case, honouring the window, and coming back empty when
    there is genuinely nothing.
    """

    def entries(self, results) -> list:
        """The matching entries, in rank order."""
        return [hit.doc.payload for hit in results.hits]

    def test_an_entry_is_found_by_headline_or_body_whatever_the_case(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """
        GIVEN: journal entries with distinctive words in their headlines and
               their bodies
        WHEN:  each is searched for, in either case
        THEN:  the entry is found, and case makes no difference
        """
        by_headline = self.entries(search_journal("JIRA-1234", days_back=0))
        by_body = self.entries(search_journal("root cause", days_back=0))

        with check:
            assert any("JIRA-1234" in e.headline for e in by_headline)
        with check:
            assert any("root cause" in e.content.lower() for e in by_body)
        with check:
            assert len(search_journal("meeting", days_back=0).hits) == len(
                search_journal("MEETING", days_back=0).hits
            )

    def test_a_search_for_something_absent_comes_back_empty(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """
        GIVEN: a query naming something that appears nowhere
        WHEN:  it is searched for
        THEN:  no entries are returned, and the unknown term is reported

        An existence check has to be able to fail. Ranking is generous about
        what matches, so this is the guarantee most at risk from it: a term
        the corpus has never seen is excluded from matching rather than
        loosely matched, and when every term is unknown the answer is nothing.
        """
        results = search_journal("xyzzy-not-found-anywhere", days_back=0)

        with check:
            assert not results.hits
        with check:
            assert results.absent_terms == ["xyzzy-not-found-anywhere"]

    def test_the_window_bounds_which_days_are_searched(
        self, temp_org_dir: Path
    ) -> None:
        """
        GIVEN: entries written today and ten days ago
        WHEN:  the search window is narrower than, then wider than, that gap
        THEN:  only the entries inside the window are returned

        The window has three spellings -- days_back, since and until -- and
        all of them resolve through one function, so they cannot disagree.
        """
        journal_dir = temp_org_dir / "journal"
        today = date.today()
        old_date = today - timedelta(days=10)

        (journal_dir / today.strftime("%Y%m%d")).write_text(
            make_journal_file(
                [make_journal_entry("10:00", "Today unique marker")], today
            )
        )
        (journal_dir / old_date.strftime("%Y%m%d")).write_text(
            make_journal_file(
                [make_journal_entry("10:00", "Old unique marker")], old_date
            )
        )

        narrow = self.entries(search_journal("unique marker", days_back=5))
        wide = self.entries(search_journal("unique marker", days_back=15))
        dated = self.entries(
            search_journal(
                "unique marker", days_back=0, since=today.isoformat()
            )
        )

        with check:
            assert len(narrow) == 1
        with check:
            assert "Today" in narrow[0].headline
        with check:
            assert len(wide) == 2
        with check:
            assert len(dated) == 1, "since should bound it like days_back"

    def test_results_can_be_narrowed_to_tags_or_to_headlines(
        self, temp_org_dir: Path
    ) -> None:
        """
        GIVEN: entries where a word appears in one entry's headline and
               another entry's body, one of them tagged
        WHEN:  the search is restricted by tag, and separately to headlines
        THEN:  each restriction returns only the entry it should

        headline_only asks what an entry is *about* rather than what it
        happens to mention, which is the difference between finding the entry
        on a subject and finding every entry that referred to it in passing.
        """
        today = date.today()
        (temp_org_dir / "journal" / today.strftime("%Y%m%d")).write_text(
            make_journal_file(
                [
                    "** 09:00 Quernstone rollout :decision:\n- the headline one",
                    "** 10:00 Unrelated work\n- mentions quernstone in passing",
                ],
                today,
            )
        )

        tagged = self.entries(
            search_journal("quernstone", days_back=0, tags=["decision"])
        )
        headlines = self.entries(
            search_journal("quernstone", days_back=0, headline_only=True)
        )
        everything = self.entries(search_journal("quernstone", days_back=0))

        with check:
            assert len(everything) == 2, "both entries mention it"
        with check:
            assert [e.time for e in tagged] == ["09:00"]
        with check:
            assert [e.time for e in headlines] == ["09:00"]

    def test_a_ranked_search_puts_the_better_match_first(
        self, temp_org_dir: Path
    ) -> None:
        """
        GIVEN: two entries, one about the subject and one mentioning it once
        WHEN:  the subject is searched for by relevance
        THEN:  the entry about it ranks first, and each hit reports how much
               of the query it covered
        """
        today = date.today()
        (temp_org_dir / "journal" / today.strftime("%Y%m%d")).write_text(
            make_journal_file(
                [
                    "** 09:00 Passing mention\n- we also touched quernstone",
                    "** 10:00 Quernstone design review\n- quernstone shape "
                    "and quernstone tradeoffs",
                ],
                today,
            )
        )

        results = search_journal(
            "quernstone design", days_back=0, order="relevance"
        )

        with check:
            assert results.hits[0].doc.payload.time == "10:00"
        with check:
            assert results.hits[0].matched_terms == 2
        with check:
            assert all(h.total_terms == 2 for h in results.hits)
