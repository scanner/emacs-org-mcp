"""Tests for environment variable configuration."""

import importlib
import os
from collections.abc import Generator
from pathlib import Path

import pytest
from pytest_mock import MockerFixture


class TestEnvironmentVariableConfiguration:
    """Tests that environment variables correctly configure the server."""

    @pytest.fixture(autouse=True)
    def reload_server_after_test(self) -> Generator[None, None, None]:
        """Reload server module after each test to restore default config."""
        yield
        # After test completes (and mocker restores os.environ), reload to get defaults
        import server

        importlib.reload(server)

    def test_default_values(self) -> None:
        """
        Given no environment variables are set
        When the server module is loaded
        Then all configuration values should use their defaults
        """
        import server

        assert server.ORG_DIR == Path.home() / "org"
        assert server.TASKS_FILE == Path.home() / "org" / "tasks.org"
        assert server.JOURNAL_DIR == Path.home() / "org" / "journal"
        assert server.ACTIVE_SECTION == "Tasks"
        assert server.COMPLETED_SECTION == "Completed Tasks"
        assert server.HIGH_LEVEL_SECTION == "High Level Tasks (in order)"

    def test_custom_values_from_environment(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given custom environment variables are set
        When the server module is loaded
        Then all configuration values should use the custom values
        """
        import server

        custom_env = {
            "ORG_DIR": "/my/org",
            "JOURNAL_DIR": "/my/journal",
            "ACTIVE_SECTION": "Active Task List",
            "COMPLETED_SECTION": "Completed Task List",
            "HIGH_LEVEL_SECTION": "Task Overview",
        }
        mocker.patch.dict(os.environ, custom_env)
        importlib.reload(server)

        assert server.ORG_DIR == Path("/my/org")
        assert server.TASKS_FILE == Path("/my/org/tasks.org")
        assert server.JOURNAL_DIR == Path("/my/journal")
        assert server.ACTIVE_SECTION == "Active Task List"
        assert server.COMPLETED_SECTION == "Completed Task List"
        assert server.HIGH_LEVEL_SECTION == "Task Overview"
