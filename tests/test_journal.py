"""Tests for journal-related server functions."""

from datetime import date, timedelta
from pathlib import Path

import server
from tests.conftest import (
    JournalFilesInfo,
    make_journal_entry,
    make_journal_file,
)


class TestGetJournalPath:
    """Tests for get_journal_path function."""

    def test_path_format(self, empty_journal_dir: Path) -> None:
        """Test that journal path uses YYYYMMDD format."""
        path = server.get_journal_path(date(2025, 1, 15))

        assert path.name == "20250115"

    def test_path_in_journal_dir(self, empty_journal_dir: Path) -> None:
        """Test that path is within the journal directory."""
        path = server.get_journal_path(date(2025, 12, 22))

        assert path.parent == empty_journal_dir

    def test_finds_file_with_org_extension(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that journal files with .org extension are found."""
        target_date = date(2025, 6, 15)
        org_file = empty_journal_dir / "20250615.org"
        org_file.write_text("* 2025-06-15\n\n** 10:00 Test entry\n- Content\n")

        path = server.get_journal_path(target_date)

        assert path == org_file
        assert path.suffix == ".org"

    def test_prefers_org_extension_over_no_extension(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that .org extension is preferred when both files exist."""
        target_date = date(2025, 7, 20)
        no_ext_file = empty_journal_dir / "20250720"
        org_file = empty_journal_dir / "20250720.org"
        no_ext_file.write_text("* 2025-07-20\n\n** 09:00 No extension\n")
        org_file.write_text("* 2025-07-20\n\n** 09:00 With org extension\n")

        path = server.get_journal_path(target_date)

        assert path == org_file

    def test_parses_entries_from_org_extension_file(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that entries are correctly parsed from .org files."""
        org_file = empty_journal_dir / "20250810.org"
        org_file.write_text(
            "* 2025-08-10\n\n"
            "** 14:30 JIRA-1234 Test with org extension\n"
            "- Did something\n"
        )

        entries = server.parse_journal_entries(org_file)

        assert len(entries) == 1
        assert entries[0].time == "14:30"
        assert entries[0].headline == "JIRA-1234 Test with org extension"
        assert entries[0].file_date == "20250810"  # Should be without .org

    def test_new_file_uses_org_extension_when_existing_files_have_it(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that new files use .org extension when existing files have it."""
        # Create an existing file with .org extension
        existing = empty_journal_dir / "20250101.org"
        existing.write_text("* 2025-01-01\n")

        # Get path for a new date (file doesn't exist)
        new_date = date(2025, 9, 15)
        path = server.get_journal_path(new_date)

        assert path.suffix == ".org"
        assert path.name == "20250915.org"

    def test_new_file_uses_no_extension_when_existing_files_have_none(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that new files use no extension when existing files have none."""
        # Create an existing file without extension
        existing = empty_journal_dir / "20250101"
        existing.write_text("* 2025-01-01\n")

        # Get path for a new date (file doesn't exist)
        new_date = date(2025, 9, 15)
        path = server.get_journal_path(new_date)

        assert path.suffix == ""
        assert path.name == "20250915"


class TestParseJournalEntries:
    """Tests for parse_journal_entries function."""

    def test_parse_entries(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test parsing entries from a journal file."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )

        assert len(entries) == sample_journal_files["today_entry_count"]

    def test_parse_entry_fields(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test that parsed entries have correct fields."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )

        # Check first entry
        entry = entries[0]
        assert entry.time == "09:00"
        assert "JIRA-1234" in entry.headline
        assert entry.file_date == sample_journal_files["today"].strftime(
            "%Y%m%d"
        )

    def test_parse_entry_with_tags(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test that tags are correctly parsed."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )

        # Find the entry with daily_summary tag
        tagged_entries = [e for e in entries if "daily_summary" in e.tags]
        assert len(tagged_entries) == 1

    def test_parse_nonexistent_file(self, empty_journal_dir: Path) -> None:
        """Test parsing a nonexistent file returns empty list."""
        nonexistent = empty_journal_dir / "19700101"
        entries = server.parse_journal_entries(nonexistent)

        assert entries == []


class TestCreateJournalEntry:
    """Tests for create_journal_entry function."""

    def test_create_entry_in_new_file(self, empty_journal_dir: Path) -> None:
        """Test creating an entry when no journal file exists."""
        target_date = date(2025, 3, 15)

        result = server.create_journal_entry(
            target_date=target_date,
            time_str="10:00",
            headline="First entry of the day",
            content="- Did something\n- Did something else",
        )

        returned_date, entry = result
        assert returned_date == target_date
        assert entry.time == "10:00"
        assert entry.headline == "First entry of the day"

        # Verify file was created
        journal_file = empty_journal_dir / "20250315"
        assert journal_file.exists()

        # Verify entry can be parsed
        entries = server.parse_journal_entries(journal_file)
        assert len(entries) == 1
        assert entries[0].time == "10:00"
        assert entries[0].headline == "First entry of the day"

    def test_create_entry_appends_to_existing(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test creating an entry appends to existing file."""
        original_count = sample_journal_files["today_entry_count"]

        server.create_journal_entry(
            target_date=sample_journal_files["today"],
            time_str="20:00",
            headline="Evening update",
            content="- Late night work",
        )

        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        assert len(entries) == original_count + 1

        # New entry should be last
        assert entries[-1].time == "20:00"

    def test_create_entry_with_tags(self, empty_journal_dir: Path) -> None:
        """Test creating an entry with tags."""
        target_date = date(2025, 4, 1)

        server.create_journal_entry(
            target_date=target_date,
            time_str="17:00",
            headline="End of day",
            content="- Summary",
            tags=["daily_summary"],
        )

        journal_file = empty_journal_dir / "20250401"
        entries = server.parse_journal_entries(journal_file)

        assert len(entries) == 1
        assert "daily_summary" in entries[0].tags

    def test_create_entry_creates_date_header(
        self, empty_journal_dir: Path
    ) -> None:
        """Test that new journal file has proper date header."""
        target_date = date(2025, 5, 20)

        server.create_journal_entry(
            target_date=target_date,
            time_str="09:00",
            headline="Test",
            content="- Content",
        )

        journal_file = empty_journal_dir / "20250520"
        content = journal_file.read_text()

        assert content.startswith("* 2025-05-20")


class TestUpdateJournalEntry:
    """Tests for update_journal_entry function."""

    def test_update_entry_headline(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test updating an entry's headline."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        first_entry = entries[0]

        result = server.update_journal_entry(
            file_path=sample_journal_files["today_file"],
            line_number=first_entry.line_number,
            time_str=first_entry.time,
            headline="Updated headline",
            content=first_entry.content,
        )

        old_entry, new_entry, _ = result
        assert old_entry.headline == first_entry.headline
        assert new_entry.headline == "Updated headline"

        # Verify the update
        updated_entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        assert updated_entries[0].headline == "Updated headline"

    def test_update_entry_content(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test updating an entry's content."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        first_entry = entries[0]

        server.update_journal_entry(
            file_path=sample_journal_files["today_file"],
            line_number=first_entry.line_number,
            time_str=first_entry.time,
            headline=first_entry.headline,
            content="- New bullet point\n- Another new point",
        )

        updated_entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        assert "New bullet point" in updated_entries[0].content

    def test_update_entry_tags(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test updating an entry's tags."""
        entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        first_entry = entries[0]

        server.update_journal_entry(
            file_path=sample_journal_files["today_file"],
            line_number=first_entry.line_number,
            time_str=first_entry.time,
            headline=first_entry.headline,
            content=first_entry.content,
            tags=["new_tag", "another_tag"],
        )

        updated_entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        assert "new_tag" in updated_entries[0].tags
        assert "another_tag" in updated_entries[0].tags

    def test_update_preserves_other_entries(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test that updating one entry doesn't affect others."""
        original_entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )
        original_count = len(original_entries)
        first_entry = original_entries[0]
        second_entry = original_entries[1]

        server.update_journal_entry(
            file_path=sample_journal_files["today_file"],
            line_number=first_entry.line_number,
            time_str=first_entry.time,
            headline="Modified first entry",
            content="- Modified content",
        )

        updated_entries = server.parse_journal_entries(
            sample_journal_files["today_file"]
        )

        # Same number of entries
        assert len(updated_entries) == original_count

        # Second entry unchanged
        assert updated_entries[1].headline == second_entry.headline
        assert updated_entries[1].time == second_entry.time


class TestSearchJournal:
    """Tests for search_journal function."""

    def test_search_by_headline(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test searching journal entries by headline."""
        results = server.search_journal("JIRA-1234")

        assert len(results) >= 1
        assert any("JIRA-1234" in e.headline for e in results)

    def test_search_by_content(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test searching journal entries by content."""
        results = server.search_journal("root cause")

        assert len(results) >= 1
        assert any("root cause" in e.content.lower() for e in results)

    def test_search_case_insensitive(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test that search is case-insensitive."""
        results_lower = server.search_journal("meeting")
        results_upper = server.search_journal("MEETING")

        assert len(results_lower) == len(results_upper)

    def test_search_no_results(
        self, sample_journal_files: JournalFilesInfo
    ) -> None:
        """Test search with no matching results."""
        results = server.search_journal("xyzzy-not-found-anywhere")

        assert len(results) == 0

    def test_search_days_back_limit(self, temp_org_dir: Path) -> None:
        """Test that days_back parameter limits search scope."""
        journal_dir = temp_org_dir / "journal"

        # Create entries for today and 10 days ago
        today = date.today()
        old_date = today - timedelta(days=10)

        today_entry = make_journal_entry("10:00", "Today unique marker")
        old_entry = make_journal_entry("10:00", "Old unique marker")

        today_file = journal_dir / today.strftime("%Y%m%d")
        old_file = journal_dir / old_date.strftime("%Y%m%d")

        today_file.write_text(make_journal_file([today_entry], today))
        old_file.write_text(make_journal_file([old_entry], old_date))

        # Search with 5 days back - should only find today's
        results_5_days = server.search_journal("unique marker", days_back=5)
        assert len(results_5_days) == 1
        assert "Today" in results_5_days[0].headline

        # Search with 15 days back - should find both
        results_15_days = server.search_journal("unique marker", days_back=15)
        assert len(results_15_days) == 2
