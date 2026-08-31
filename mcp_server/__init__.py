"""
emacs-org-mcp server package.

Importing this package registers the MCP tool and resource handlers
via their decorator side-effects in ``tools`` and ``resources``.
"""

# orgmunge's drawer tokenizer can swallow whole sections, which has already
# cost us data.  Patch it before anything imports it and builds a parser.
#
import mcp_server.orgmunge_patch

mcp_server.orgmunge_patch.apply_drawer_fix()

import mcp_server.resources  # noqa: E402, F401 — registers @server.list_resources / @server.read_resource
import mcp_server.tools  # noqa: E402, F401 — registers @server.list_tools / @server.call_tool
