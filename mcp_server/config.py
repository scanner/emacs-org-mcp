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
    journal_dir: Path = Path.home() / "org" / "journal"
    projects_dir: Path = Path.home() / "org" / "projects"
    emacsclient_path: Path = Path("/usr/local/bin/emacsclient")
    ediff_approval: bool = True
    active_section: str = "Tasks"
    completed_section: str = "Completed Tasks"
    high_level_section: str = "High Level Tasks (in order)"

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
    "--active-section": "active_section",
    "--completed-section": "completed_section",
    "--high-level-section": "high_level_section",
}


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
                    if cli_arg == "--no-ediff-approval":
                        config_map[config_field] = not bool(cli_value)
                    else:
                        config_map[config_field] = bool(cli_value)
                case pathlib.Path:
                    config_map[config_field] = Path(str(cli_value)).expanduser()
                case _:
                    config_map[config_field] = cli_value

    # Create Config instance with overrides
    config = Config(**config_map)

    # If org_dir was customized, default subdirectories that weren't
    # explicitly set.
    if "org_dir" in config_map:
        if "journal_dir" not in config_map:
            config.journal_dir = config.org_dir / "journal"
        if "projects_dir" not in config_map:
            config.projects_dir = config.org_dir / "projects"

    return config


# Global state - config will be updated in __main__ after parsing args
global_state = GlobalState()
