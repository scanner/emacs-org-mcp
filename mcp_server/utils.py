"""
Shared utilities: timestamps, file I/O, diff, and ediff approval integration.
"""

# system imports
import difflib
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# project imports
from mcp_server.config import global_state, logger

# =============================================================================
# Timestamp Utilities
# =============================================================================


###############################################################################
#
def format_org_timestamp(dt: datetime, active: bool = True) -> str:
    """
    Format a datetime as an org-mode timestamp.

    Args:
        dt: The datetime to format (should be naive, in local timezone)
        active: True for active timestamp <...>, False for inactive [...]

    Returns:
        Formatted org-mode timestamp string

    Examples:
        Active: <2025-12-26 Thu 01:45>
        Inactive: [2025-12-26 Thu 01:45]

    Note:
        Expects naive timestamps in the timezone of the running Emacs instance.
        Org-mode timestamps do not support timezone information.
    """
    # Format: <YYYY-MM-DD DDD HH:MM> or [YYYY-MM-DD DDD HH:MM]
    day_abbr = dt.strftime("%a")
    timestamp = dt.strftime(f"%Y-%m-%d {day_abbr} %H:%M")

    if active:
        return f"<{timestamp}>"
    else:
        return f"[{timestamp}]"


###############################################################################
#
def get_current_timestamp(active: bool = True) -> str:
    """
    Get current time as an org-mode timestamp.

    Args:
        active: True for active timestamp <...>, False for inactive [...]

    Returns:
        Current timestamp as org-mode formatted string

    Note:
        Uses local timezone without timezone information per org-mode spec.
    """
    return format_org_timestamp(datetime.now(), active=active)


# =============================================================================
# Plain Text Formatting Utilities
# =============================================================================


###############################################################################
#
def format_simple_diff(old_content: str, new_content: str) -> str:
    """
    Create a simple diff showing only changed lines with − and + markers.

    Args:
        old_content: Original content to compare from
        new_content: New content to compare against

    Returns:
        Formatted diff string with − for removed lines and + for added lines,
        or "(no changes)" if contents are identical
    """
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    if old_lines == new_lines:
        return "(no changes)"

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    diff_lines: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        match tag:
            case "equal":
                continue
            case "replace":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"− {line}")
                for line in new_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")
            case "delete":
                for line in old_lines[i1:i2]:
                    diff_lines.append(f"− {line}")
            case "insert":
                for line in new_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")

    return "\n".join(diff_lines) if diff_lines else "(no changes)"


# =============================================================================
# File I/O Utilities
# =============================================================================


###############################################################################
#
def write_file(path: Path, content: str) -> None:
    """
    Write content to file, ensuring it ends with newline.

    Args:
        path: Path to write to
        content: Content to write

    Note:
        Creates parent directories if they don't exist.
        Automatically adds trailing newline if not present.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


###############################################################################
#
def backup_file(path: Path) -> Path:
    """
    Create a timestamped backup before modifications.

    Args:
        path: Path to the file to backup

    Returns:
        Path to the backup file (original path with timestamp suffix)

    Note:
        Does nothing if file doesn't exist (returns original path).
        Backup format: original.YYYYMMDD_HHMMSS.bak
        Caller should remove backup after successful write operation.
    """
    if not path.exists():
        return path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".{timestamp}.bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


# =============================================================================
# Ediff Approval Integration
# =============================================================================


###############################################################################
#
def get_emacsclient_path() -> str | None:
    """
    Get path to emacsclient, checking config first.

    Returns:
        Path to emacsclient executable, or None if not found
    """
    # Check configured path
    configured_path = global_state.config.emacsclient_path
    if configured_path.exists():
        return str(configured_path)

    # Fall back to PATH search
    return shutil.which("emacsclient")


###############################################################################
#
def is_ediff_approval_enabled() -> bool:
    """
    Check if ediff approval is enabled and available.

    Returns:
        True if ediff_approval config is enabled and emacsclient is available
    """
    ediff_enabled = global_state.config.ediff_approval
    logger.info("Checking ediff approval: ediff_approval=%r", ediff_enabled)

    if not ediff_enabled:
        logger.info("Ediff approval disabled in config")
        return False

    emacsclient = get_emacsclient_path()
    if emacsclient is None:
        logger.warning("Ediff approval enabled but emacsclient not found")
        return False

    logger.info("Ediff approval enabled, emacsclient found at %s", emacsclient)
    return True


###############################################################################
#
def ensure_elisp_loaded(force: bool = False) -> None:
    """
    Load emacs_ediff.el if not already loaded.

    Args:
        force: If True, reload even if already loaded (useful for development)
    """
    if global_state.elisp_loaded and not force:
        return

    emacsclient = get_emacsclient_path()
    if not emacsclient:
        return

    elisp_path = Path(__file__).parent.parent / "emacs_ediff.el"
    if not elisp_path.exists():
        logger.warning("emacs_ediff.el not found at %s", elisp_path)
        return

    try:
        subprocess.run(
            [emacsclient, "--eval", f'(load-file "{elisp_path}")'],
            capture_output=True,
            check=True,
            timeout=5,
        )
        global_state.elisp_loaded = True
        logger.info("Loaded emacs_ediff.el")
    except Exception as e:
        logger.warning("Failed to load emacs_ediff.el: %r", e)


###############################################################################
#
def request_ediff_approval(
    old_content: str, new_content: str, context_name: str
) -> tuple[bool, str]:
    """
    Present old vs new content in Emacs ediff for approval. The default for
    various failure and misconfiguration is to basically consider the new
    content approved.

    XXX More work should be done to report problems to the user

    Args:
        old_content: Current content (empty string for creates)
        new_content: Proposed new content
        context_name: Context identifier for filenames (e.g., "gh-127", "20250107-1430")

    Returns:
        (approved, final_content) where final_content may be user-edited
    """
    logger.info("request_ediff_approval called for context: %s", context_name)

    if not is_ediff_approval_enabled():
        logger.info("Ediff approval not enabled, auto-approving")
        return (True, new_content)

    emacsclient = get_emacsclient_path()
    if not emacsclient:
        logger.warning("emacsclient not found, auto-approving")
        return (True, new_content)

    logger.info("Starting ediff approval workflow for %s", context_name)
    ensure_elisp_loaded()

    # Create temp directory with context-specific files
    #
    with tempfile.TemporaryDirectory(prefix="emacs-org-mcp-ediff-") as tempdir:
        tempdir_path = Path(tempdir)
        old_file = tempdir_path / f"old-{context_name}.org"
        new_file = tempdir_path / f"new-{context_name}.org"

        try:
            old_file.write_text(old_content, encoding="utf-8")
            new_file.write_text(new_content, encoding="utf-8")

            result = subprocess.run(
                [
                    emacsclient,
                    "--eval",
                    f'(org-mcp-ediff-approve "{old_file}" "{new_file}")',
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=300,  # 5 minute timeout
            )

            decision = result.stdout.strip().strip('"')

            if decision == "approved":
                final_content = new_file.read_text(encoding="utf-8")
                return (True, final_content)
            return (False, new_content)

        except subprocess.TimeoutExpired:
            logger.warning("Ediff approval timed out, auto-rejecting")
            return (False, new_content)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "Ediff approval failed with exit code %d, auto-approving",
                e.returncode,
            )
            logger.warning("stdout: %s", e.stdout)
            logger.warning("stderr: %s", e.stderr)
            return (True, new_content)
        except Exception as e:
            logger.warning("Ediff approval failed: %r, auto-approving", e)
            return (True, new_content)
