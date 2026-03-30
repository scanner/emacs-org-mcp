#!/usr/bin/env python3
"""MCP Server for Emacs Org-Mode Tasks, Journal, and Project Management

Usage:
  server.py [--ediff-approval] [--no-ediff-approval] [--org-dir=<path>] [--journal-dir=<path>]
            [--projects-dir=<path>] [--active-section=<name>] [--completed-section=<name>]
            [--high-level-section=<name>] [--emacsclient-path=<path>]
  server.py (-h | --help)
  server.py --version

Options:
  --ediff-approval              Enable ediff approval (default, kept for backwards compatibility)
  --no-ediff-approval           Disable ediff approval
  --org-dir=<path>              Base org directory [default: ~/org]
  --journal-dir=<path>          Journal directory (defaults to <org-dir>/journal)
  --projects-dir=<path>         Projects directory (defaults to <org-dir>/projects)
  --active-section=<name>       Active tasks section [default: Tasks]
  --completed-section=<name>    Completed tasks section [default: Completed Tasks]
  --high-level-section=<name>   High level tasks section [default: High Level Tasks (in order)]
  --emacsclient-path=<path>     Path to emacsclient
  -h --help                     Show this help
  --version                     Show version

Configuration Priority:
  1. Command-line arguments (highest)
  2. Environment variables (EMACS_EDIFF_APPROVAL, ORG_DIR, etc.)
  3. Defaults (lowest)

Uses orgmunge for robust org-mode file manipulation.
Designed for use with Claude CLI/Code/Desktop to manage:
- ~/org/tasks.org (task tracking with Active/Completed sections)
- ~/org/journal/YYYYMMDD (daily journal entries)
- ~/org/projects/<slug>.org (project files with index)
"""

# system imports
import asyncio
import logging

# 3rd party imports
from docopt import docopt
from mcp.server import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities

# project imports — importing mcp_server registers all MCP tool/resource handlers
import mcp_server  # noqa: F401
from mcp_server.config import global_state, load_config, server


###############################################################################
#
async def main() -> None:
    """Run the MCP server over stdio."""
    init_options = InitializationOptions(
        server_name="emacs-org-mode",
        server_version="0.1.0",
        capabilities=ServerCapabilities(),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)


###############################################################################
###############################################################################
#
if __name__ == "__main__":
    # Configure logging to stderr (MCP clients capture this)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler()],  # Outputs to stderr by default
    )

    # Parse command-line arguments and load configuration
    args = docopt(__doc__, version="0.1.1")
    global_state.config = load_config(args)

    asyncio.run(main())
