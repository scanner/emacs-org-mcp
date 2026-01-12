"""Tests for MCP resource listing and reading."""

import asyncio
from pathlib import Path

import pytest

import server


class TestLoadGuide:
    """Tests for the load_guide() helper function."""

    @pytest.mark.parametrize(
        "filename",
        [
            "task-format.md",
            "journal-format.md",
            "tool-usage.md",
            "examples.md",
        ],
    )
    def test_load_guide_returns_file_content(self, filename: str) -> None:
        """
        Given a guide file exists
        When load_guide is called
        Then it should return the exact file contents
        """
        guides_dir = Path(__file__).parent.parent / "resources" / "guides"
        expected = (guides_dir / filename).read_text()
        actual = server.load_guide(filename)
        assert actual == expected

    def test_load_nonexistent_guide(self) -> None:
        """
        Given a guide file does not exist
        When load_guide is called with a non-existent filename
        Then it should raise FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            server.load_guide("nonexistent.md")


class TestResourceContentGenerators:
    """Tests for the resource content generator functions."""

    @pytest.mark.parametrize(
        "func,filename",
        [
            (server.get_task_format_guide, "task-format.md"),
            (server.get_journal_format_guide, "journal-format.md"),
            (server.get_tool_usage_guide, "tool-usage.md"),
            (server.get_examples_guide, "examples.md"),
        ],
    )
    def test_guide_generator_returns_file_content(
        self, func, filename: str
    ) -> None:
        """
        Given a guide generator function is called
        When it loads its guide file
        Then it should return the exact file contents
        """
        guides_dir = Path(__file__).parent.parent / "resources" / "guides"
        expected = (guides_dir / filename).read_text()
        actual = func()
        assert actual == expected


class TestListResources:
    """Tests for the list_resources() function."""

    def test_list_resources_includes_all_guides(self) -> None:
        """
        Given list_resources is called
        When it returns the list of available resources
        Then it should include all four guide resources
        """
        resources = asyncio.run(server.list_resources())

        guide_uris = [
            "emacs-org://guide/task-format",
            "emacs-org://guide/journal-format",
            "emacs-org://guide/tool-usage",
            "emacs-org://guide/examples",
        ]

        actual_uris = [str(r.uri) for r in resources]
        for uri in guide_uris:
            assert uri in actual_uris, f"Resource {uri} should be in list"


class TestReadResource:
    """Tests for the read_resource() function."""

    @pytest.mark.parametrize(
        "uri,filename",
        [
            ("emacs-org://guide/task-format", "task-format.md"),
            ("emacs-org://guide/journal-format", "journal-format.md"),
            ("emacs-org://guide/tool-usage", "tool-usage.md"),
            ("emacs-org://guide/examples", "examples.md"),
        ],
    )
    def test_read_resource_returns_file_content(
        self, uri: str, filename: str
    ) -> None:
        """
        Given read_resource is called with a guide URI
        When it loads the resource
        Then it should return ReadResourceContents with the exact file contents
        """
        guides_dir = Path(__file__).parent.parent / "resources" / "guides"
        expected = (guides_dir / filename).read_text()
        result = asyncio.run(server.read_resource(uri))

        # read_resource now returns list[ReadResourceContents]
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].content == expected
        assert result[0].mime_type == "text/markdown"

    def test_read_resource_unknown(self) -> None:
        """
        Given read_resource is called with an unknown URI
        When it attempts to load the resource
        Then it should raise ValueError
        """
        with pytest.raises(ValueError, match="Unknown resource"):
            asyncio.run(server.read_resource("emacs-org://guide/nonexistent"))

    def test_all_listed_guides_are_readable(self) -> None:
        """
        Given all guide resources from list_resources
        When each guide is read via read_resource
        Then all should successfully return the file contents
        """
        guides_dir = Path(__file__).parent.parent / "resources" / "guides"
        resources = asyncio.run(server.list_resources())

        guide_resources = [
            r for r in resources if str(r.uri).startswith("emacs-org://guide/")
        ]

        # Map URIs to filenames
        uri_to_file = {
            "emacs-org://guide/task-format": "task-format.md",
            "emacs-org://guide/journal-format": "journal-format.md",
            "emacs-org://guide/tool-usage": "tool-usage.md",
            "emacs-org://guide/examples": "examples.md",
        }

        for resource in guide_resources:
            uri_str = str(resource.uri)
            expected = (guides_dir / uri_to_file[uri_str]).read_text()
            result = asyncio.run(server.read_resource(uri_str))

            # read_resource now returns list[ReadResourceContents]
            assert isinstance(result, list)
            assert len(result) == 1
            assert (
                result[0].content == expected
            ), f"Resource {uri_str} should return file contents"
