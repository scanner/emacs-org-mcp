#!/usr/bin/env python
#
"""
Tests for where a setting comes from and where the org paths end up.

Two promises. A setting arrives from a command-line option, an environment
variable or a default, and the more specific source wins. And every org path
a Config exposes lives under that Config's own ``org_dir`` -- which is the
one that has been broken, with a Config built directly reading its tasks from
the directory it was given while writing projects to the user's live files.
"""

# system imports
import os
from pathlib import Path

# 3rd party imports
import pytest
from pytest_check import check
from pytest_mock import MockerFixture

# project imports
from mcp_server.config import Config, load_config

# =============================================================================
# Defaults
# =============================================================================


###############################################################################
###############################################################################
#
class TestDefaults:
    """What a Config holds when nothing is given."""

    ###########################################################################
    #
    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(lambda: Config(), id="constructed"),
            pytest.param(lambda: load_config({}), id="loaded"),
        ],
    )
    def test_the_documented_defaults_hold_however_a_config_is_built(
        self, mocker: MockerFixture, build
    ):
        """
        GIVEN: A Config with nothing given, built either directly or through
               the loader
         WHEN: Its settings are read
         THEN: They are the documented defaults, the same either way

        The two routes are checked together because they disagreeing is the
        failure this has actually had: the loader repaired paths the
        constructor got wrong, so the server was correct and every direct
        construction was not.
        """
        mocker.patch.dict(os.environ, {}, clear=True)

        config = build()
        org = Path.home() / "org"

        with check:
            assert config.org_dir == org
        with check:
            assert config.journal_dir == org / "journal"
        with check:
            assert config.projects_dir == org / "projects"
        with check:
            assert config.tasks_file == org / "tasks.org"
        with check:
            assert config.search_roots == [org]
        with check:
            assert config.ediff_approval is True
        with check:
            assert config.active_section == "Tasks"
        with check:
            assert config.completed_section == "Completed Tasks"
        with check:
            assert config.high_level_section == "High Level Tasks (in order)"


# =============================================================================
# Sources and precedence
# =============================================================================

# Every setting that can arrive by either route, as
# (env var, cli option, given value, attribute, expected).
SETTINGS = [
    ("ORG_DIR", "--org-dir", "/given/org", "org_dir", Path("/given/org")),
    (
        "JOURNAL_DIR",
        "--journal-dir",
        "/given/journal",
        "journal_dir",
        Path("/given/journal"),
    ),
    (
        "PROJECTS_DIR",
        "--projects-dir",
        "/given/projects",
        "projects_dir",
        Path("/given/projects"),
    ),
    (
        "EMACSCLIENT_PATH",
        "--emacsclient-path",
        "/given/emacsclient",
        "emacsclient_path",
        Path("/given/emacsclient"),
    ),
    (
        "ACTIVE_SECTION",
        "--active-section",
        "Given Active",
        "active_section",
        "Given Active",
    ),
    (
        "COMPLETED_SECTION",
        "--completed-section",
        "Given Completed",
        "completed_section",
        "Given Completed",
    ),
    (
        "HIGH_LEVEL_SECTION",
        "--high-level-section",
        "Given Overview",
        "high_level_section",
        "Given Overview",
    ),
]


###############################################################################
###############################################################################
#
class TestWhereASettingComesFrom:
    """Which source supplies a value, and which one wins."""

    ###########################################################################
    #
    @pytest.mark.parametrize("source", ["environment", "command line"])
    def test_every_setting_arrives_by_either_route(
        self, mocker: MockerFixture, source: str
    ):
        """
        GIVEN: Every setting supplied at once, as environment variables or as
               command-line options
         WHEN: Configuration is loaded
         THEN: Each value is used whichever way it arrived, and a path is
               turned into a Path rather than left as text

        Both routes are checked for every setting because they are wired one
        setting at a time, so reachable one way and not the other is the shape
        this mistake takes. They are checked together so one unwired setting
        names itself instead of hiding the rest behind the first failure.
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {}

        for env_var, cli_option, given, _, _ in SETTINGS:
            if source == "environment":
                mocker.patch.dict(os.environ, {env_var: given})
            else:
                args[cli_option] = given

        config = load_config(args)

        for _, _, _, attribute, expected in SETTINGS:
            with check:
                assert getattr(config, attribute) == expected, attribute

    ###########################################################################
    #
    def test_the_command_line_wins_over_the_environment(
        self, mocker: MockerFixture
    ):
        """
        GIVEN: A setting named both in the environment and on the command line
         WHEN: Configuration is loaded
         THEN: The command line is used, since it is the more deliberate of
               the two -- typed for this run, where the environment persists
          AND: A setting named only in the environment still comes through, so
               winning is per setting rather than the command line replacing
               the environment wholesale
        """
        mocker.patch.dict(
            os.environ,
            {
                "ORG_DIR": "/from/env",
                "EMACS_EDIFF_APPROVAL": "false",
                "ACTIVE_SECTION": "From Env",
            },
            clear=True,
        )

        config = load_config(
            {"--org-dir": "/from/cli", "--ediff-approval": True}
        )

        with check:
            assert config.org_dir == Path("/from/cli")
        with check:
            assert config.ediff_approval is True
        with check:
            assert config.active_section == "From Env"

    ###########################################################################
    #
    def test_an_option_that_was_not_given_is_not_a_value(
        self, mocker: MockerFixture
    ):
        """
        GIVEN: A command-line option present in the parsed arguments but set
               to None, which is how an option nobody typed arrives
         WHEN: Configuration is loaded
         THEN: It does not count as a value: the environment is consulted, and
               the default is used where the environment is silent

        Were None taken as an answer, every option the user did not type would
        blank out their environment.
        """
        mocker.patch.dict(
            os.environ, {"ACTIVE_SECTION": "From Env"}, clear=True
        )

        config = load_config(
            {
                "--org-dir": None,
                "--active-section": None,
                "--ediff-approval": True,
            }
        )

        with check:
            assert config.org_dir == Path.home() / "org"
        with check:
            assert config.active_section == "From Env"
        with check:
            assert config.ediff_approval is True

    ###########################################################################
    #
    @pytest.mark.parametrize(
        "expected, spellings",
        [
            pytest.param(
                True,
                ("true", "True", "TRUE", "1", "yes", "Yes", "YES"),
                id="on",
            ),
            pytest.param(
                False,
                ("false", "False", "FALSE", "0", "no", "No", "NO", ""),
                id="off",
            ),
        ],
    )
    def test_a_boolean_reads_the_way_people_spell_it(
        self, mocker: MockerFixture, expected: bool, spellings: tuple[str, ...]
    ):
        """
        GIVEN: A boolean setting written the way someone would write it in a
               shell -- any case, a digit, or yes/no
         WHEN: Configuration is loaded
         THEN: It reads as the boolean they meant, and a spelling that is not
               recognised reads as off rather than as the truthiness of a
               non-empty string, which would make "false" mean true
        """
        for spelling in spellings:
            mocker.patch.dict(
                os.environ, {"EMACS_EDIFF_APPROVAL": spelling}, clear=True
            )

            with check:
                assert load_config({}).ediff_approval is expected, spelling

    ###########################################################################
    #
    @pytest.mark.parametrize(
        "env_value, cli_option, expected",
        [
            pytest.param(None, None, True, id="on-by-default"),
            pytest.param(None, "--no-ediff-approval", False, id="off-by-flag"),
            pytest.param(None, "--ediff-approval", True, id="on-by-flag"),
            pytest.param(
                "true", "--no-ediff-approval", False, id="flag-beats-env-on"
            ),
            pytest.param(
                "false", "--ediff-approval", True, id="flag-beats-env-off"
            ),
            pytest.param("false", None, False, id="env-beats-default"),
            pytest.param("true", None, True, id="env-agrees-with-default"),
        ],
    )
    def test_ediff_approval_settles_the_same_way_from_either_flag(
        self,
        mocker: MockerFixture,
        env_value: str | None,
        cli_option: str | None,
        expected: bool,
    ):
        """
        GIVEN: Ediff approval named by the environment, by --ediff-approval,
               by --no-ediff-approval, or by nothing at all
         WHEN: Configuration is loaded
         THEN: It is on unless something turns it off, and a flag beats the
               environment either way round

        This one setting has two spellings on the command line, so it is the
        one where a flag can be wired to set a value but not to clear it.
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        if env_value is not None:
            mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": env_value})

        args: dict[str, str | bool | None] = (
            {cli_option: True} if cli_option else {}
        )

        assert load_config(args).ediff_approval is expected

    ###########################################################################
    #
    def test_a_tilde_becomes_a_real_path(self, mocker: MockerFixture):
        """
        GIVEN: A directory written with a leading ~, as it would be in a shell
               profile
         WHEN: Configuration is loaded
         THEN: It is expanded to the home directory, because nothing below
               this point expands one and a literal "~" directory would be
               created next to wherever the server was started
        """
        mocker.patch.dict(
            os.environ,
            {"ORG_DIR": "~/my/org", "JOURNAL_DIR": "~/my/journal"},
            clear=True,
        )

        config = load_config({})

        with check:
            assert config.org_dir == Path.home() / "my" / "org"
        with check:
            assert config.journal_dir == Path.home() / "my" / "journal"


# =============================================================================
# Containment
# =============================================================================


###############################################################################
###############################################################################
#
class TestPathsFollowOrgDir:
    """
    Every org path a Config exposes lives under that Config's org_dir.

    This was not true. journal_dir and projects_dir had their own defaults
    pointing at the real org directory, and only load_config repaired them --
    so a Config built directly, by a test or a script, read its tasks from the
    directory it was given and wrote projects to the user's live files. It did
    exactly that once.
    """

    ###########################################################################
    #
    def test_every_path_follows_a_custom_org_dir(self, tmp_path: Path):
        """
        GIVEN: A Config given only an org_dir
         WHEN: Its paths are read
         THEN: Every one of them is under that org_dir, the search roots
               included -- a root left pointing at the real org directory
               would have the server reading the user's files during a test

        Stated as containment rather than as equality per path, because what
        matters is that nothing escapes, not the spelling of each one.
        """
        config = Config(org_dir=tmp_path)
        paths = [
            config.journal_dir,
            config.projects_dir,
            config.tasks_file,
            *config.search_roots,
        ]

        for path in paths:
            with check:
                assert path == tmp_path or tmp_path in path.parents, (
                    f"{path} is outside the given org_dir"
                )

    ###########################################################################
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
        GIVEN: A Config given an org_dir, and possibly an explicit
               subdirectory
         WHEN: Its paths are read
         THEN: The explicit one is kept and the other is derived

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

    ###########################################################################
    #
    @pytest.mark.parametrize("source", ["environment", "command line"])
    def test_the_loader_derives_the_directory_that_was_not_named(
        self, tmp_path: Path, mocker: MockerFixture, source: str
    ):
        """
        GIVEN: An org directory and one explicit subdirectory, by either route
         WHEN: Configuration is loaded
         THEN: The explicit subdirectory is kept and the other is derived from
               the org directory

        The loader used to do this derivation itself. Moving it into Config
        has to leave the loader's behaviour unchanged by both routes, since
        each is wired separately.
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        args: dict[str, str | bool | None] = {}

        if source == "environment":
            mocker.patch.dict(
                os.environ,
                {
                    "ORG_DIR": str(tmp_path),
                    "PROJECTS_DIR": str(tmp_path / "custom"),
                },
            )
        else:
            args["--org-dir"] = str(tmp_path)
            args["--projects-dir"] = str(tmp_path / "custom")

        config = load_config(args)

        with check:
            assert config.projects_dir == tmp_path / "custom"
        with check:
            assert config.journal_dir == tmp_path / "journal"
