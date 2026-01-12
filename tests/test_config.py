"""Tests for configuration loading via CLI args and environment variables."""

import os
from pathlib import Path

from pytest_mock import MockerFixture

import server


class TestLoadConfig:
    """Tests for the load_config() function."""

    def test_default_values(self) -> None:
        """
        Given no CLI args or environment variables
        When load_config is called
        Then all configuration values should use their defaults
        """
        config = server.load_config({})

        assert config.org_dir == Path.home() / "org"
        assert config.journal_dir == Path.home() / "org" / "journal"
        assert config.emacsclient_path == Path("/usr/local/bin/emacsclient")
        assert config.ediff_approval is False
        assert config.active_section == "Tasks"
        assert config.completed_section == "Completed Tasks"
        assert config.high_level_section == "High Level Tasks (in order)"

    def test_property_tasks_file(self) -> None:
        """
        Given a config with org_dir set
        When accessing tasks_file property
        Then it should return org_dir / tasks.org
        """
        config = server.Config(org_dir=Path("/custom/org"))

        assert config.tasks_file == Path("/custom/org/tasks.org")

    def test_environment_variable_loading(self, mocker: MockerFixture) -> None:
        """
        Given environment variables are set
        When load_config is called with empty args
        Then config should use environment variable values
        """
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "/my/org",
                "JOURNAL_DIR": "/my/journal",
                "EMACSCLIENT_PATH": "/usr/bin/emacsclient",
                "EMACS_EDIFF_APPROVAL": "true",
                "ACTIVE_SECTION": "Active Task List",
                "COMPLETED_SECTION": "Completed Task List",
                "HIGH_LEVEL_SECTION": "Task Overview",
            },
        )

        config = server.load_config({})

        assert config.org_dir == Path("/my/org")
        assert config.journal_dir == Path("/my/journal")
        assert config.emacsclient_path == Path("/usr/bin/emacsclient")
        assert config.ediff_approval is True
        assert config.active_section == "Active Task List"
        assert config.completed_section == "Completed Task List"
        assert config.high_level_section == "Task Overview"

    def test_cli_argument_loading(self) -> None:
        """
        Given CLI arguments are provided
        When load_config is called
        Then config should use CLI argument values
        """
        args: dict[str, str | bool | None] = {
            "--org-dir": "/cli/org",
            "--journal-dir": "/cli/journal",
            "--emacsclient-path": "/opt/emacsclient",
            "--ediff-approval": True,
            "--active-section": "CLI Active",
            "--completed-section": "CLI Completed",
            "--high-level-section": "CLI High Level",
        }

        config = server.load_config(args)

        assert config.org_dir == Path("/cli/org")
        assert config.journal_dir == Path("/cli/journal")
        assert config.emacsclient_path == Path("/opt/emacsclient")
        assert config.ediff_approval is True
        assert config.active_section == "CLI Active"
        assert config.completed_section == "CLI Completed"
        assert config.high_level_section == "CLI High Level"

    def test_cli_overrides_environment(self, mocker: MockerFixture) -> None:
        """
        Given both environment variables and CLI arguments are set
        When load_config is called
        Then CLI arguments should take priority over environment variables
        """
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "/env/org",
                "EMACS_EDIFF_APPROVAL": "false",
                "ACTIVE_SECTION": "Env Active",
            },
        )

        args: dict[str, str | bool | None] = {
            "--org-dir": "/cli/org",
            "--ediff-approval": True,
            # active_section not in CLI, should use env value
        }

        config = server.load_config(args)

        assert config.org_dir == Path("/cli/org")  # CLI wins
        assert config.ediff_approval is True  # CLI wins
        assert config.active_section == "Env Active"  # Env used when no CLI

    def test_bool_type_conversion_true_values(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given ediff_approval is set to various truthy strings
        When load_config is called
        Then config.ediff_approval should be True
        """
        for value in ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]:
            mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": value})
            config = server.load_config({})
            assert (
                config.ediff_approval is True
            ), f"Expected True for value: {value}"

    def test_bool_type_conversion_false_values(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given ediff_approval is set to non-truthy strings
        When load_config is called
        Then config.ediff_approval should be False
        """
        for value in ["false", "False", "FALSE", "0", "no", "No", "NO", ""]:
            mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": value})
            config = server.load_config({})
            assert (
                config.ediff_approval is False
            ), f"Expected False for value: {value}"

    def test_path_expansion_tilde(self, mocker: MockerFixture) -> None:
        """
        Given paths with ~ (tilde) are provided
        When load_config is called
        Then paths should be expanded to absolute paths
        """
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "~/my/org",
                "JOURNAL_DIR": "~/my/journal",
            },
        )

        config = server.load_config({})

        assert config.org_dir == Path.home() / "my" / "org"
        assert config.journal_dir == Path.home() / "my" / "journal"
        # Should not contain ~ in the path
        assert "~" not in str(config.org_dir)
        assert "~" not in str(config.journal_dir)

    def test_none_cli_args_ignored(self, mocker: MockerFixture) -> None:
        """
        Given CLI args dict contains None values (not provided)
        When load_config is called
        Then None values should be ignored and not override env/defaults
        """
        mocker.patch.dict(os.environ, {"ACTIVE_SECTION": "Env Section"})

        args: dict[str, str | bool | None] = {
            "--org-dir": None,  # Not provided
            "--active-section": None,  # Not provided
            "--ediff-approval": True,  # Provided
        }

        config = server.load_config(args)

        assert config.org_dir == Path.home() / "org"  # Default
        assert config.active_section == "Env Section"  # Env
        assert config.ediff_approval is True  # CLI

    def test_journal_dir_defaults_to_org_dir_when_org_dir_customized(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given org_dir is customized but journal_dir is not
        When load_config is called
        Then journal_dir should default to org_dir/journal
        """
        # Test with environment variable
        mocker.patch.dict(os.environ, {"ORG_DIR": "/custom/org"})
        config = server.load_config({})
        assert config.org_dir == Path("/custom/org")
        assert config.journal_dir == Path("/custom/org/journal")

        # Test with CLI argument
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {
            "--org-dir": "/another/org",
        }
        config = server.load_config(args)
        assert config.org_dir == Path("/another/org")
        assert config.journal_dir == Path("/another/org/journal")

    def test_journal_dir_not_overridden_when_explicitly_set(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given both org_dir and journal_dir are customized
        When load_config is called
        Then journal_dir should use the explicitly set value
        """
        # Test with environment variables
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "/custom/org",
                "JOURNAL_DIR": "/completely/different/journal",
            },
        )
        config = server.load_config({})
        assert config.org_dir == Path("/custom/org")
        assert config.journal_dir == Path("/completely/different/journal")

        # Test with CLI arguments
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {
            "--org-dir": "/another/org",
            "--journal-dir": "/separate/journal",
        }
        config = server.load_config(args)
        assert config.org_dir == Path("/another/org")
        assert config.journal_dir == Path("/separate/journal")
