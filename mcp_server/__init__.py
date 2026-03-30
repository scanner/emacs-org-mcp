"""
emacs-org-mcp server package.

Importing this package registers the MCP tool and resource handlers
via their decorator side-effects in ``tools`` and ``resources``.
"""

import mcp_server.resources  # noqa: F401 — registers @server.list_resources / @server.read_resource
import mcp_server.tools  # noqa: F401 — registers @server.list_tools / @server.call_tool
