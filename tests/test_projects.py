#!/usr/bin/env python
#
"""Test project operations for the MCP server."""

# system imports
from pathlib import Path

# 3rd party imports
import pytest

# project imports
import server
from tests.conftest import ProjectFilesInfo


########################################################################
#
class TestParseProjectFile:
    """Tests for parsing project .org files."""

    ####################################################################
    #
    def test_parse_project_fields_and_sections(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project file with all standard fields and sections
        WHEN:  parse_project_file is called
        THEN:  all fields and sections are correctly extracted
        """
        projects_dir = sample_project_files["projects_dir"]
        project = server.parse_project_file(
            projects_dir / "booklore.org"
        )

        assert project.title == "Booklore: Local Fiction RAG Platform"
        assert project.slug == "booklore"
        assert project.custom_id == "project-booklore"
        assert project.id == "AAAA-BBBB-CCCC-1111"
        assert project.status == "active"
        assert "project" in project.tags
        assert project.repo == "https://github.com/scanner/booklore"
        assert project.created == "<2026-01-15 Thu 10:00>"
        # Sections
        assert "RAG platform" in project.description
        assert "EPUB extraction" in project.goals
        assert "Qdrant" in project.sections["Notes"]

    ####################################################################
    #
    def test_parse_nonexistent_file(
        self, temp_org_dir: Path
    ) -> None:
        """
        GIVEN: a path to a non-existent file
        WHEN:  parse_project_file is called
        THEN:  FileNotFoundError is raised
        """
        with pytest.raises(FileNotFoundError):
            server.parse_project_file(
                temp_org_dir / "projects" / "nope.org"
            )

    ####################################################################
    #
    def test_parse_slug_from_filename_when_no_custom_id(
        self, temp_org_dir: Path
    ) -> None:
        """
        GIVEN: a project file without CUSTOM_ID
        WHEN:  parse_project_file is called
        THEN:  slug is derived from filename
        """
        projects_dir = temp_org_dir / "projects"
        content = (
            "* My Project  :project:\n"
            ":PROPERTIES:\n"
            "   :ID:       TEST-1\n"
            ":END:\n"
        )
        (projects_dir / "my-project.org").write_text(content)

        project = server.parse_project_file(
            projects_dir / "my-project.org"
        )
        assert project.slug == "my-project"


########################################################################
#
class TestListProjects:
    """Tests for listing projects."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "status,expected_count",
        [
            (None, 3),
            ("active", 1),
            ("completed", 1),
            ("planning", 1),
            ("on-hold", 0),
        ],
    )
    def test_list_projects_by_status(
        self,
        sample_project_files: ProjectFilesInfo,
        status: str | None,
        expected_count: int,
    ) -> None:
        """
        GIVEN: a projects directory with projects of various statuses
        WHEN:  list_projects is called with an optional status filter
        THEN:  the correct number of projects is returned
        """
        projects = server.list_projects(status=status)
        assert len(projects) == expected_count
        # When unfiltered, results should be sorted by title
        if status is None:
            titles = [p.title for p in projects]
            assert titles == sorted(titles)

    ####################################################################
    #
    def test_list_excludes_index_file(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a projects directory containing an index.org
        WHEN:  list_projects is called
        THEN:  index.org is not included in results
        """
        projects_dir = sample_project_files["projects_dir"]
        (projects_dir / "index.org").write_text(
            "* Projects Index\nAuto-generated.\n"
        )

        projects = server.list_projects()
        slugs = [p.slug for p in projects]
        assert "index" not in slugs

    ####################################################################
    #
    def test_list_empty_directory(
        self, empty_projects_dir: Path
    ) -> None:
        """
        GIVEN: an empty projects directory
        WHEN:  list_projects is called
        THEN:  an empty list is returned
        """
        assert server.list_projects() == []


########################################################################
#
class TestGetProject:
    """Tests for finding a specific project."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "identifier",
        [
            "booklore",
            "project-booklore",
            "Booklore",
            "Fiction RAG",
        ],
    )
    def test_get_project_by_various_identifiers(
        self,
        sample_project_files: ProjectFilesInfo,
        identifier: str,
    ) -> None:
        """
        GIVEN: a project file exists
        WHEN:  get_project is called with slug, CUSTOM_ID, or title
        THEN:  the correct project is returned
        """
        project = server.get_project(identifier)
        assert project.slug == "booklore"

    ####################################################################
    #
    def test_get_project_not_found(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: no project matching the identifier
        WHEN:  get_project is called
        THEN:  ValueError is raised
        """
        with pytest.raises(ValueError, match="No project found"):
            server.get_project("nonexistent-project")


########################################################################
#
class TestCreateProject:
    """Tests for creating new projects."""

    ####################################################################
    #
    def test_create_project_with_auto_filled_defaults(
        self, empty_projects_dir: Path
    ) -> None:
        """
        GIVEN: a minimal project entry (no ID, timestamps, or status)
        WHEN:  create_project is called
        THEN:  file is created with auto-generated ID, timestamps,
               default status, and :project: tag
        """
        entry = (
            "* Auto Fill Test\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: project-auto-fill\n"
            ":END:\n\n"
            "** Description\nTesting auto-fill.\n"
        )
        slug, content = server.create_project(entry)

        assert slug == "auto-fill"
        project = server.parse_project_file(
            empty_projects_dir / "auto-fill.org"
        )
        assert len(project.id) == 36  # UUID
        assert project.created  # Non-empty
        assert project.modified  # Non-empty
        assert project.status == "planning"
        assert "project" in project.tags

    ####################################################################
    #
    def test_create_project_duplicate_slug_raises(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project with the same slug already exists
        WHEN:  create_project is called
        THEN:  ValueError is raised
        """
        entry = (
            "* Duplicate  :project:\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: project-booklore\n"
            ":END:\n"
        )
        with pytest.raises(ValueError, match="already exists"):
            server.create_project(entry)

    ####################################################################
    #
    def test_create_project_regenerates_index(
        self, empty_projects_dir: Path
    ) -> None:
        """
        GIVEN: a new project is created
        WHEN:  create_project completes
        THEN:  index.org is generated with the new project
        """
        entry = (
            "* Index Test  :project:\n"
            ":PROPERTIES:\n"
            "   :CUSTOM_ID: project-index-test\n"
            ":END:\n\n"
            "** Description\nTesting index generation.\n"
        )
        server.create_project(entry)

        index_path = empty_projects_dir / "index.org"
        assert index_path.exists()
        assert "Index Test" in index_path.read_text()


########################################################################
#
class TestUpdateProject:
    """Tests for updating existing projects."""

    ####################################################################
    #
    def test_update_section_preserves_others(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project with multiple sections
        WHEN:  one section is updated
        THEN:  that section changes, others are preserved,
               and MODIFIED timestamp is updated
        """
        original = server.get_project("booklore")

        server.update_project(
            identifier="booklore",
            section="Description",
            content="Updated description for Booklore.",
        )

        updated = server.get_project("booklore")
        assert "Updated description" in updated.description
        assert "Goals" in updated.sections
        assert updated.sections.get("Notes", "") == original.sections.get("Notes", "")
        assert updated.modified != original.modified

    ####################################################################
    #
    def test_update_properties(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: an existing project
        WHEN:  update_project is called with a STATUS change
        THEN:  the property is updated in the file
        """
        server.update_project(
            identifier="booklore",
            properties={"STATUS": "on-hold"},
        )

        project = server.get_project("booklore")
        assert project.status == "on-hold"

    ####################################################################
    #
    def test_update_adds_missing_section(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project without a Design section
        WHEN:  update_project adds a Design section
        THEN:  the section is appended to the file
        """
        server.update_project(
            identifier="booklore",
            section="Design",
            content="New design notes here.",
        )

        project = server.get_project("booklore")
        assert "design notes" in project.sections["Design"]

    ####################################################################
    #
    def test_update_headline(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: an existing project
        WHEN:  update_project is called with a new headline
        THEN:  the title is changed
        """
        server.update_project(
            identifier="booklore",
            headline="Booklore: Fiction Search Engine",
        )

        project = server.get_project("booklore")
        assert project.title == "Booklore: Fiction Search Engine"

    ####################################################################
    #
    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({}, "At least one"),
            ({"properties": {"STATUS": "bogus"}}, "Invalid status"),
        ],
    )
    def test_update_validation_errors(
        self,
        sample_project_files: ProjectFilesInfo,
        kwargs: dict,
        match: str,
    ) -> None:
        """
        GIVEN: invalid update parameters
        WHEN:  update_project is called
        THEN:  ValueError is raised with appropriate message
        """
        with pytest.raises(ValueError, match=match):
            server.update_project(
                identifier="booklore", **kwargs
            )


########################################################################
#
class TestReplaceProjectSection:
    """Tests for the section replacement helper."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "section_name,new_content",
        [
            ("Description", "New desc."),
            ("Notes", "Updated notes."),
        ],
    )
    def test_replace_existing_section(
        self,
        section_name: str,
        new_content: str,
    ) -> None:
        """
        GIVEN: file content with existing sections
        WHEN:  replace_project_section is called
        THEN:  the target section body is replaced
        """
        file_content = (
            "* Project  :project:\n"
            ":PROPERTIES:\n:END:\n\n"
            "** Description\nOld desc.\n\n"
            "** Notes\nOld notes.\n"
        )

        result = server.replace_project_section(
            file_content, section_name, new_content
        )
        assert new_content in result

    ####################################################################
    #
    def test_append_new_section(self) -> None:
        """
        GIVEN: file content without the target section
        WHEN:  replace_project_section is called
        THEN:  the section is appended at the end
        """
        file_content = (
            "* Project  :project:\n"
            ":PROPERTIES:\n:END:\n\n"
            "** Description\nSome desc.\n"
        )

        result = server.replace_project_section(
            file_content, "Design", "Architecture notes."
        )
        assert "** Design" in result
        assert "Architecture notes." in result


########################################################################
#
class TestSearchProjects:
    """Tests for searching across projects."""

    ####################################################################
    #
    @pytest.mark.parametrize(
        "query,expected_slug",
        [
            ("Booklore", "booklore"),
            ("Qdrant", "booklore"),
            ("Modernization", "infra"),
        ],
    )
    def test_search_finds_matching_projects(
        self,
        sample_project_files: ProjectFilesInfo,
        query: str,
        expected_slug: str,
    ) -> None:
        """
        GIVEN: projects with distinct titles and content
        WHEN:  search_projects is called
        THEN:  the correct project is found (case-insensitive)
        """
        results = server.search_projects(query)
        assert len(results) == 1
        assert results[0].slug == expected_slug

    ####################################################################
    #
    def test_search_no_results(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a query matching no projects
        WHEN:  search_projects is called
        THEN:  an empty list is returned
        """
        assert server.search_projects("xyzzy-nonexistent") == []


########################################################################
#
class TestRegenerateProjectIndex:
    """Tests for the project index auto-generation."""

    ####################################################################
    #
    def test_index_groups_by_status_with_links(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: projects with different statuses
        WHEN:  regenerate_project_index is called
        THEN:  index.org groups them by status with org-mode links
        """
        server.regenerate_project_index()

        index_path = (
            sample_project_files["projects_dir"] / "index.org"
        )
        content = index_path.read_text()

        assert "** Active" in content
        assert "** Completed" in content
        assert "** Planning" in content
        assert "[[file:" in content
        assert "booklore.org" in content

    ####################################################################
    #
    def test_index_empty_directory(
        self, empty_projects_dir: Path
    ) -> None:
        """
        GIVEN: no project files exist
        WHEN:  regenerate_project_index is called
        THEN:  index.org is created with just the header
        """
        server.regenerate_project_index()

        index_path = empty_projects_dir / "index.org"
        assert index_path.exists()
        assert "Projects Index" in index_path.read_text()


########################################################################
#
class TestLinkTaskToProject:
    """Tests for linking tasks to projects."""

    ####################################################################
    #
    def test_link_adds_to_related_tasks(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project exists
        WHEN:  link_task_to_project is called
        THEN:  the task link appears in Related Tasks section
        """
        task_link = "- [[file:~/org/tasks.org::#task-gh-99][GH-99 Test task]]"
        server.link_task_to_project("booklore", task_link)

        project = server.get_project("booklore")
        assert "GH-99" in project.sections["Related Tasks"]

    ####################################################################
    #
    def test_link_creates_section_if_missing(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a project without a Related Tasks section
        WHEN:  link_task_to_project is called
        THEN:  the section is created with the link
        """
        task_link = "- [[file:~/org/tasks.org::#task-gh-55][GH-55 New task]]"
        server.link_task_to_project("email-migration", task_link)

        project = server.get_project("email-migration")
        assert "GH-55" in project.sections["Related Tasks"]


########################################################################
#
class TestProjectToOrg:
    """Tests for the Project.to_org() serialization."""

    ####################################################################
    #
    def test_to_org_roundtrip(
        self, sample_project_files: ProjectFilesInfo
    ) -> None:
        """
        GIVEN: a parsed project
        WHEN:  to_org() is called and re-parsed
        THEN:  the key fields survive the roundtrip
        """
        original = server.get_project("booklore")
        org_text = original.to_org()

        temp_path = (
            sample_project_files["projects_dir"] / "_roundtrip.org"
        )
        temp_path.write_text(org_text)
        reparsed = server.parse_project_file(temp_path)

        assert reparsed.title == original.title
        assert reparsed.custom_id == original.custom_id
        assert reparsed.status == original.status
        assert reparsed.repo == original.repo
        assert "Description" in reparsed.sections
        assert "Goals" in reparsed.sections
