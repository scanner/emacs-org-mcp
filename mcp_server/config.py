"""
Configuration, constants, and global state for the MCP server.
"""

# system imports
import builtins
import logging
import os
import pathlib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

# 3rd party imports
from mcp.server import Server

# =============================================================================
# MCP Server Instance
# =============================================================================

server = Server("emacs-org-mode")
logger = logging.getLogger("mcp_server")


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class Config:
    """Configuration for the MCP server."""

    org_dir: Path = Path.home() / "org"

    # Left unset so that __post_init__ can tell "not given" from "given", and
    # derive these from org_dir. They are typed Path because that is what they
    # always are once construction finishes, and because load_config reads the
    # declared type to convert environment variables -- widening it to
    # Path | None would stop JOURNAL_DIR and PROJECTS_DIR being converted at
    # all.
    journal_dir: Path = None  # type: ignore[assignment]
    projects_dir: Path = None  # type: ignore[assignment]

    # Directories walked for loose org files. Left unset for the same reason
    # as the two above, and it matters more here: a default naming the real
    # org directory would make every Config built for a temp directory read
    # the user's own files.
    search_roots: list[Path] = None  # type: ignore[assignment]
    emacsclient_path: Path = Path("/usr/local/bin/emacsclient")
    ediff_approval: bool = True
    git_autocommit: bool = True
    active_section: str = "Tasks"
    completed_section: str = "Completed Tasks"
    high_level_section: str = "High Level Tasks (in order)"

    ###########################################################################
    #
    def __post_init__(self) -> None:
        """
        Derive the subdirectories from org_dir unless they were given.

        Note:
            This has to live here rather than in a loader. A Config built
            directly -- by a test, a script, or any tooling -- otherwise keeps
            the *default* journal and projects directories while taking its
            tasks file from the org_dir it was given, so it reads tasks from
            one place and writes projects to the user's real org directory.
            That is not hypothetical: it happened, and it wrote to live data.

            Only tasks_file was safe before, because it alone was derived.
        """
        if self.journal_dir is None:
            self.journal_dir = self.org_dir / "journal"
        if self.projects_dir is None:
            self.projects_dir = self.org_dir / "projects"
        if self.search_roots is None:
            self.search_roots = [self.org_dir]

    ###########################################################################
    #
    @property
    def tasks_file(self) -> Path:
        """Return the path to the tasks.org file."""
        return self.org_dir / "tasks.org"


@dataclass
class GlobalState:
    """
    A way to hold global state that can be modified from code without
    requiring the use of a `global` statement.
    """

    config: Config = field(default_factory=Config)
    elisp_loaded: bool = False


# Configuration field types for type conversion
CONFIG_FIELD_TYPES = {fld.name: fld.type for fld in fields(Config)}

# Mapping of environment variables to Config fields
ENV_VAR_TO_CONFIG = {
    "ORG_DIR": "org_dir",
    "JOURNAL_DIR": "journal_dir",
    "PROJECTS_DIR": "projects_dir",
    "EMACSCLIENT_PATH": "emacsclient_path",
    "EMACS_EDIFF_APPROVAL": "ediff_approval",
    "GIT_AUTOCOMMIT": "git_autocommit",
    "ACTIVE_SECTION": "active_section",
    "COMPLETED_SECTION": "completed_section",
    "HIGH_LEVEL_SECTION": "high_level_section",
}

# Mapping of CLI arguments to Config fields
CLI_ARG_TO_CONFIG = {
    "--org-dir": "org_dir",
    "--journal-dir": "journal_dir",
    "--projects-dir": "projects_dir",
    "--emacsclient-path": "emacsclient_path",
    "--ediff-approval": "ediff_approval",
    "--no-ediff-approval": "ediff_approval",
    "--git-autocommit": "git_autocommit",
    "--no-git-autocommit": "git_autocommit",
    "--active-section": "active_section",
    "--completed-section": "completed_section",
    "--high-level-section": "high_level_section",
}


###############################################################################
#
def parse_search_roots(value: str) -> list[Path]:
    """
    Read search roots from a path-separated environment variable.

    Args:
        value: Directories joined by the platform's path separator, as
            `SEARCH_ROOTS` gives them

    Returns:
        The directories, with `~` expanded. Empty when nothing was set,
        which leaves Config to derive the default from org_dir.

    Note:
        Separated by `os.pathsep` rather than a comma, so this behaves like
        PATH on the platform it runs on. A comma is a legal character in a
        directory name and a colon is not, on the systems this runs on.
    """
    return [
        Path(part).expanduser()
        for part in value.split(os.pathsep)
        if part.strip()
    ]


###############################################################################
#
def load_config(args: dict[str, str | bool | None]) -> Config:
    """
    Load configuration from CLI arguments and environment variables.

    Configuration priority (highest to lowest):
    1. Command-line arguments
    2. Environment variables
    3. Defaults from Config dataclass

    Args:
        args: Parsed command-line arguments from docopt

    Returns:
        Configured Config instance
    """
    config_map: dict[str, Any] = {}

    # search_roots is the one list-valued setting, so it is read here rather
    # than taught to the type-matching below. The CLI flag is repeatable and
    # wins outright over the environment variable rather than extending it,
    # which is how every other setting behaves.
    #
    roots = parse_search_roots(os.environ.get("SEARCH_ROOTS", ""))
    cli_roots: Any = args.get("--search-root") or []
    if isinstance(cli_roots, list) and cli_roots:
        roots = [Path(str(root)).expanduser() for root in cli_roots]
    if roots:
        config_map["search_roots"] = roots

    # Load from environment variables
    #
    for env_var, config_field in ENV_VAR_TO_CONFIG.items():
        if env_var in os.environ:
            field_type = CONFIG_FIELD_TYPES[config_field]
            value = os.environ[env_var]

            # Convert the value from a string to the expected type for each
            # parameter specified.
            #
            match field_type:
                case builtins.bool:
                    config_map[config_field] = value.lower() in (
                        "true",
                        "1",
                        "yes",
                    )
                case pathlib.Path:
                    config_map[config_field] = Path(value).expanduser()
                case _:
                    config_map[config_field] = value

    # Load from CLI arguments (overrides environment variables)
    for cli_arg, config_field in CLI_ARG_TO_CONFIG.items():
        cli_value = args.get(cli_arg)
        if cli_value is not None:
            field_type = CONFIG_FIELD_TYPES[config_field]

            # Type conversion
            match field_type:
                case builtins.bool:
                    # Boolean flags are directly True/False from docopt
                    # Special handling: --no-ediff-approval inverts the value
                    if cli_arg in (
                        "--no-ediff-approval",
                        "--no-git-autocommit",
                    ):
                        config_map[config_field] = not bool(cli_value)
                    else:
                        config_map[config_field] = bool(cli_value)
                case pathlib.Path:
                    config_map[config_field] = Path(str(cli_value)).expanduser()
                case _:
                    config_map[config_field] = cli_value

    # Create Config instance with overrides
    # Config derives journal_dir and projects_dir from org_dir itself, so
    # anything not named here follows the org_dir given.
    return Config(**config_map)


# Global state - config will be updated in __main__ after parsing args
global_state = GlobalState()
