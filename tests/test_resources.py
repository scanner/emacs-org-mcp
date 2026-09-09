#!/usr/bin/env python
#
"""
Tests for the documentation the server hands clients as MCP resources.

The guides are how a client learns the task, journal and project formats
without the user writing them into a config file, so the promises here are
that the server advertises them, that reading one returns the file on disk
rather than a stale copy compiled in, and that the two agree -- a guide
listed but not readable is a link to nothing.
"""

# system imports
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import cast

# 3rd party imports
import pytest

# project imports
from mcp_server.resources import list_resources, load_guide, read_resource

# =============================================================================
# Constants
# =============================================================================

GUIDES_DIR = Path(__file__).parent.parent / "resources" / "guides"

GUIDE_URI_PREFIX = "emacs-org://guide/"

# The guides the server is expected to offer. Named here so that dropping one
# from the listing is a failure rather than one fewer loop iteration.
GUIDE_URIS = (
    "emacs-org://guide/task-format",
    "emacs-org://guide/journal-format",
    "emacs-org://guide/project-format",
)


###############################################################################
#
def guide_file_for(uri: str) -> Path:
    """The file a guide URI names, by the server's own convention."""
    return GUIDES_DIR / f"{uri.removeprefix(GUIDE_URI_PREFIX)}.md"


# =============================================================================
# Capabilities
# =============================================================================


###############################################################################
###############################################################################
#
class TestServerCapabilities:
    """What the server tells a client it can do."""

    ###########################################################################
    #
    @pytest.fixture
    def server_init_response(self) -> dict[str, object]:
        """Run the real server and perform the MCP initialize handshake."""
        server_py = Path(__file__).parent.parent / "server.py"
        init_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            }
        )
        result = subprocess.run(
            [sys.executable, str(server_py)],
            input=init_request,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return cast(dict[str, object], json.loads(result.stdout.strip()))

    ###########################################################################
    #
    @pytest.mark.parametrize("capability", ["resources", "tools"])
    def test_a_capability_the_server_has_is_advertised(
        self, server_init_response: dict, capability: str
    ):
        """
        GIVEN: A client completing the MCP initialize handshake
         WHEN: The server returns its capabilities
         THEN: Both resources and tools are named, because a client asks only
               for what was advertised -- omitting one hides every resource or
               every tool while the server keeps serving them to nobody

        Built against the real server process rather than the handler, since
        the regression this pins was in the `ServerCapabilities(...)` call and
        an in-process test would have constructed it correctly by hand.
        """
        capabilities = server_init_response["result"]["capabilities"]

        assert capability in capabilities, (
            f"ServerCapabilities() is missing '{capability}', so clients will "
            f"never request {capability}."
        )


# =============================================================================
# Guides
# =============================================================================


###############################################################################
###############################################################################
#
class TestTheGuides:
    """Reading the format documentation the server offers."""

    ###########################################################################
    #
    def test_the_format_guides_are_offered(self):
        """
        GIVEN: A client asking what resources the server has
         WHEN: The listing is returned
         THEN: All three format guides are in it, since a client that cannot
               see one has no way to ask for it
        """
        offered = {
            str(resource.uri) for resource in asyncio.run(list_resources())
        }

        assert set(GUIDE_URIS) <= offered

    ###########################################################################
    #
    def test_every_guide_offered_reads_back_as_its_file(self):
        """
        GIVEN: Each guide the server advertises
         WHEN: It is read
         THEN: It returns the file on disk, byte for byte, as markdown -- so
               editing a guide changes what clients are told, with no step in
               between
          AND: Every advertised guide reads: one that is listed but not served
               is a link to nothing, and this walks the listing rather than a
               list of its own so a newly offered guide is covered the day it
               is added
        """
        offered = [
            str(resource.uri)
            for resource in asyncio.run(list_resources())
            if str(resource.uri).startswith(GUIDE_URI_PREFIX)
        ]
        assert offered, "no guides were offered at all"

        for uri in offered:
            contents = asyncio.run(read_resource(uri))

            assert len(contents) == 1, uri
            assert contents[0].content == guide_file_for(uri).read_text(), uri
            assert contents[0].mime_type == "text/markdown", uri

    ###########################################################################
    #
    def test_an_unknown_resource_is_refused(self):
        """
        GIVEN: A URI the server serves nothing for
         WHEN: It is read
         THEN: It is refused by name, rather than returning empty content that
               a client would render as an empty guide
        """
        with pytest.raises(ValueError, match="Unknown resource"):
            asyncio.run(read_resource("emacs-org://guide/nonexistent"))

    ###########################################################################
    #
    def test_a_guide_whose_file_is_gone_is_refused(self):
        """
        GIVEN: A guide file that is not on disk
         WHEN: It is loaded
         THEN: It raises rather than returning empty text, so a packaging
               mistake that drops a guide fails loudly instead of serving a
               client an empty document
        """
        with pytest.raises(FileNotFoundError):
            load_guide("nonexistent.md")
