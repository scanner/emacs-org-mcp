"""Tests for configuration loading via CLI args and environment variables."""

import os
from pathlib import Path

import pytest
from pytest_check import check
from pytest_mock import MockerFixture

from mcp_server.config import Config, load_config


class TestLoadConfig:
    """Tests for the load_config() function."""

    def test_default_values(self) -> None:
        """
        Given no CLI args or environment variables
        When load_config is called
        Then all configuration values should use their defaults
        """
        config = load_config({})

        assert config.org_dir == Path.home() / "org"
        assert config.journal_dir == Path.home() / "org" / "journal"
        assert config.projects_dir == Path.home() / "org" / "projects"
        assert config.emacsclient_path == Path("/usr/local/bin/emacsclient")
        assert config.ediff_approval is True  # Default is now True
        assert config.active_section == "Tasks"
        assert config.completed_section == "Completed Tasks"
        assert config.high_level_section == "High Level Tasks (in order)"

    def test_property_tasks_file(self) -> None:
        """
        Given a config with org_dir set
        When accessing tasks_file property
        Then it should return org_dir / tasks.org
        """
        config = Config(org_dir=Path("/custom/org"))

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
                "PROJECTS_DIR": "/my/projects",
                "EMACSCLIENT_PATH": "/usr/bin/emacsclient",
                "EMACS_EDIFF_APPROVAL": "true",
                "ACTIVE_SECTION": "Active Task List",
                "COMPLETED_SECTION": "Completed Task List",
                "HIGH_LEVEL_SECTION": "Task Overview",
            },
        )

        config = load_config({})

        assert config.org_dir == Path("/my/org")
        assert config.journal_dir == Path("/my/journal")
        assert config.projects_dir == Path("/my/projects")
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
            "--projects-dir": "/cli/projects",
            "--emacsclient-path": "/opt/emacsclient",
            "--ediff-approval": True,
            "--active-section": "CLI Active",
            "--completed-section": "CLI Completed",
            "--high-level-section": "CLI High Level",
        }

        config = load_config(args)

        assert config.org_dir == Path("/cli/org")
        assert config.journal_dir == Path("/cli/journal")
        assert config.projects_dir == Path("/cli/projects")
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

        config = load_config(args)

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
            config = load_config({})
            assert config.ediff_approval is True, (
                f"Expected True for value: {value}"
            )

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
            config = load_config({})
            assert config.ediff_approval is False, (
                f"Expected False for value: {value}"
            )

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

        config = load_config({})

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

        config = load_config(args)

        assert config.org_dir == Path.home() / "org"  # Default
        assert config.active_section == "Env Section"  # Env
        assert config.ediff_approval is True  # CLI

    def test_subdirs_default_to_org_dir_when_org_dir_customized(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given org_dir is customized but journal_dir/projects_dir are not
        When load_config is called
        Then both default to subdirectories of org_dir
        """
        # Test with environment variable
        mocker.patch.dict(os.environ, {"ORG_DIR": "/custom/org"})
        config = load_config({})
        assert config.org_dir == Path("/custom/org")
        assert config.journal_dir == Path("/custom/org/journal")
        assert config.projects_dir == Path("/custom/org/projects")

        # Test with CLI argument
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {
            "--org-dir": "/another/org",
        }
        config = load_config(args)
        assert config.org_dir == Path("/another/org")
        assert config.journal_dir == Path("/another/org/journal")
        assert config.projects_dir == Path("/another/org/projects")

    def test_subdirs_not_overridden_when_explicitly_set(
        self, mocker: MockerFixture
    ) -> None:
        """
        Given both org_dir and journal_dir/projects_dir are customized
        When load_config is called
        Then explicitly set values are preserved
        """
        # Test with environment variables
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "/custom/org",
                "JOURNAL_DIR": "/completely/different/journal",
                "PROJECTS_DIR": "/completely/different/projects",
            },
        )
        config = load_config({})
        assert config.org_dir == Path("/custom/org")
        assert config.journal_dir == Path("/completely/different/journal")
        assert config.projects_dir == Path("/completely/different/projects")

        # Test with CLI arguments
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {
            "--org-dir": "/another/org",
            "--journal-dir": "/separate/journal",
            "--projects-dir": "/separate/projects",
        }
        config = load_config(args)
        assert config.org_dir == Path("/another/org")
        assert config.journal_dir == Path("/separate/journal")
        assert config.projects_dir == Path("/separate/projects")

    @pytest.mark.parametrize(
        "env_value,cli_arg,cli_value,expected,description",
        [
            # Test default behavior (no args, no env)
            (None, None, None, True, "default-is-true"),
            # Test --no-ediff-approval flag
            (
                None,
                "--no-ediff-approval",
                True,
                False,
                "no-ediff-flag-disables",
            ),
            # Test --ediff-approval flag (backwards compatibility)
            (None, "--ediff-approval", True, True, "ediff-flag-enables"),
            # Test --no-ediff-approval overrides env=true
            (
                "true",
                "--no-ediff-approval",
                True,
                False,
                "no-ediff-overrides-env-true",
            ),
            # Test --ediff-approval overrides env=false
            (
                "false",
                "--ediff-approval",
                True,
                True,
                "ediff-overrides-env-false",
            ),
            # Test env=false overrides default
            ("false", None, None, False, "env-false-overrides-default"),
            # Test env=true keeps default
            ("true", None, None, True, "env-true-keeps-default"),
        ],
    )
    def test_ediff_approval_flag_combinations(
        self,
        mocker: MockerFixture,
        env_value: str | None,
        cli_arg: str | None,
        cli_value: bool | None,
        expected: bool,
        description: str,
    ) -> None:
        """
        Test various combinations of environment variables and CLI flags for ediff_approval.

        This parametrized test covers:
        - Default behavior (ediff enabled)
        - --no-ediff-approval flag disables ediff
        - --ediff-approval flag explicitly enables ediff
        - CLI flags override environment variables
        - Environment variables override defaults
        """
        # Setup environment
        if env_value is not None:
            mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": env_value})
        else:
            mocker.patch.dict(os.environ, {}, clear=True)

        # Setup CLI args
        args: dict[str, str | bool | None] = {}
        if cli_arg is not None:
            args[cli_arg] = cli_value

        # Execute
        config = load_config(args)

        # Assert
        assert config.ediff_approval is expected, (
            f"Test '{description}' failed: "
            f"env={env_value}, cli_arg={cli_arg}, cli_value={cli_value}, "
            f"expected={expected}, got={config.ediff_approval}"
        )


########################################################################
########################################################################
#
class TestPathsFollowOrgDir:
    """
    Tests that every org path a Config exposes lives under its org_dir.

    This was not true. journal_dir and projects_dir had their own defaults
    pointing at the real org directory, and only load_config repaired them --
    so a Config built directly, by a test or a script, read its tasks from the
    directory it was given and wrote projects to the user's live files. It did
    exactly that once.
    """

    ####################################################################
    #
    def test_every_path_follows_a_custom_org_dir(self, tmp_path: Path):
        """
        GIVEN: a Config given only an org_dir
        WHEN:  its paths are read
        THEN:  all of them are under that org_dir

        The guarantee is stated as containment rather than as three equality
        checks, because what matters is that nothing escapes to the real org
        directory -- which is the failure this had.
        """
        config = Config(org_dir=tmp_path)

        for name in ("journal_dir", "projects_dir", "tasks_file"):
            path = getattr(config, name)
            with check:
                assert tmp_path in path.parents or path.parent == tmp_path, (
                    f"{name} is {path}, outside the given org_dir"
                )

    ####################################################################
    #
    @pytest.mark.parametrize(
        "overrides, expected",
        [
            pytest.param(
                {},
                {"journal_dir": "journal", "projects_dir": "projects"},
                id="both-derived",
            ),
            pytest.param(
                {"journal_dir": "elsewhere/j"},
                {"journal_dir": "elsewhere/j", "projects_dir": "projects"},
                id="explicit-journal-wins",
            ),
            pytest.param(
                {"projects_dir": "elsewhere/p"},
                {"journal_dir": "journal", "projects_dir": "elsewhere/p"},
                id="explicit-projects-wins",
            ),
        ],
    )
    def test_an_explicit_subdirectory_is_not_overridden(
        self, tmp_path: Path, overrides, expected
    ):
        """
        GIVEN: a Config given an org_dir, and possibly an explicit
               subdirectory
        WHEN:  its paths are read
        THEN:  the explicit one is kept and the other is derived

        Deriving must not mean overwriting: a caller that names a directory
        has said where it wants it.
        """
        config = Config(
            org_dir=tmp_path,
            **{name: tmp_path / rel for name, rel in overrides.items()},
        )

        for name, rel in expected.items():
            with check:
                assert getattr(config, name) == tmp_path / rel

    ####################################################################
    #
    def test_the_default_config_still_points_at_the_org_directory(self):
        """
        GIVEN: a Config with nothing given
        WHEN:  its paths are read
        THEN:  they are the usual ones under the home org directory

        Deriving the subdirectories must not move them for the ordinary case.
        """
        config = Config()

        with check:
            assert config.journal_dir == Path.home() / "org" / "journal"
        with check:
            assert config.projects_dir == Path.home() / "org" / "projects"

    ####################################################################
    #
    def test_load_config_still_honours_explicit_directories(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: ORG_DIR and an explicit PROJECTS_DIR in the environment
        WHEN:  configuration is loaded
        THEN:  the explicit projects directory is kept and the journal
               directory is derived

        load_config used to perform this derivation itself. Moving it into
        Config must leave the loader's behaviour unchanged.
        """
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": str(tmp_path),
                "PROJECTS_DIR": str(tmp_path / "custom"),
            },
            clear=False,
        )

        config = load_config({})

        with check:
            assert config.projects_dir == tmp_path / "custom"
        with check:
            assert config.journal_dir == tmp_path / "journal"
