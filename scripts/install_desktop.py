#!/usr/bin/env python3
"""
Install or uninstall emacs-org MCP server in Claude Desktop configuration.
"""
import json
import os
import sys


def install_server(config_path, mcp_name, uv_path, root_dir, server_script):
    """Install the MCP server configuration."""
    # Read existing config or create new one
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config = {}

    # Ensure mcpServers exists
    config.setdefault("mcpServers", {})

    # Add/update the emacs-org server configuration
    config["mcpServers"][mcp_name] = {
        "command": uv_path,
        "args": ["--directory", root_dir, "run", server_script],
        "env": {
            "ORG_DIR": os.path.expanduser("~/org"),
            "JOURNAL_DIR": os.path.expanduser("~/org/journal"),
            "ACTIVE_SECTION": "Tasks",
            "COMPLETED_SECTION": "Completed Tasks",
            "HIGH_LEVEL_SECTION": "High Level Tasks (in order)",
        },
    }

    # Write updated config
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f'MCP server "{mcp_name}" installed successfully!')


def uninstall_server(config_path, mcp_name):
    """Uninstall the MCP server configuration."""
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        print(f'MCP server "{mcp_name}" is not installed.')
        return

    with open(config_path, "r") as f:
        config = json.load(f)

    # Check if mcpServers exists and contains our server
    if "mcpServers" not in config or mcp_name not in config["mcpServers"]:
        print(f'MCP server "{mcp_name}" is not installed.')
        return

    # Remove the server
    del config["mcpServers"][mcp_name]

    # Write updated config
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f'MCP server "{mcp_name}" uninstalled successfully!')


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: install_desktop.py <install|uninstall> <config_path> <mcp_name> [<uv_path> <root_dir> <server_script>]"
        )
        sys.exit(1)

    command = sys.argv[1]
    config_path = sys.argv[2]
    mcp_name = sys.argv[3]

    if command == "install":
        if len(sys.argv) != 7:
            print(
                "Usage: install_desktop.py install <config_path> <mcp_name> <uv_path> <root_dir> <server_script>"
            )
            sys.exit(1)
        uv_path = sys.argv[4]
        root_dir = sys.argv[5]
        server_script = sys.argv[6]
        install_server(config_path, mcp_name, uv_path, root_dir, server_script)
    elif command == "uninstall":
        uninstall_server(config_path, mcp_name)
    else:
        print(f"Unknown command: {command}")
        print(
            "Usage: install_desktop.py <install|uninstall> <config_path> <mcp_name> [<uv_path> <root_dir> <server_script>]"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
