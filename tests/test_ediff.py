#!/usr/bin/env python
#
"""
Tests for ediff approval functionality.

These tests mock subprocess.run to avoid requiring a running Emacs instance.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

import server

###############################################################################
# Fixtures
###############################################################################


@pytest.fixture(autouse=True)
def reset_elisp_loaded():
    """Reset the global _elisp_loaded state before each test."""
    server.global_state.elisp_loaded = False
    yield
    server.global_state.elisp_loaded = False


###############################################################################
# Tests for get_emacsclient_path
###############################################################################


class TestGetEmacsclientPath:
    """Tests for get_emacsclient_path function."""

    def test_returns_configured_path_when_exists(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACSCLIENT_PATH env var points to existing file
        WHEN: get_emacsclient_path() is called
        THEN: Returns the configured path
        """
        fake_client = tmp_path / "my_emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_client)})

        result = server.get_emacsclient_path()

        assert result == str(fake_client)

    def test_ignores_configured_path_when_not_exists(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACSCLIENT_PATH points to nonexistent file
        WHEN: get_emacsclient_path() is called
        THEN: Falls back to shutil.which()
        """
        fake_path = tmp_path / "nonexistent"
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_path)})
        mocker.patch("shutil.which", return_value="/usr/bin/emacsclient")

        result = server.get_emacsclient_path()

        assert result == "/usr/bin/emacsclient"

    def test_falls_back_to_which_when_no_env_var(self, mocker: MockerFixture):
        """
        GIVEN: EMACSCLIENT_PATH env var is not set
        WHEN: get_emacsclient_path() is called
        THEN: Uses shutil.which() to find emacsclient
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("shutil.which", return_value="/usr/local/bin/emacsclient")

        result = server.get_emacsclient_path()

        assert result == "/usr/local/bin/emacsclient"

    def test_returns_none_when_not_found(self, mocker: MockerFixture):
        """
        GIVEN: emacsclient is not found anywhere
        WHEN: get_emacsclient_path() is called
        THEN: Returns None
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("shutil.which", return_value=None)

        result = server.get_emacsclient_path()

        assert result is None


###############################################################################
# Tests for is_ediff_approval_enabled
###############################################################################


class TestIsEdiffApprovalEnabled:
    """Tests for is_ediff_approval_enabled function."""

    def test_returns_true_when_enabled_and_emacsclient_available(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACS_EDIFF_APPROVAL=true and emacsclient available
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns True
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        result = server.is_ediff_approval_enabled()

        assert result is True

    def test_returns_false_when_disabled(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACS_EDIFF_APPROVAL=false
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns False
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "false",
            },
        )

        result = server.is_ediff_approval_enabled()

        assert result is False

    def test_returns_false_when_env_var_not_set(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACS_EDIFF_APPROVAL is not set
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns False
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_client)})

        result = server.is_ediff_approval_enabled()

        assert result is False

    def test_accepts_various_truthy_values(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: EMACS_EDIFF_APPROVAL set to various truthy values
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns True for all accepted values
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")

        for value in ["true", "1", "yes", "TRUE", "YES"]:
            mocker.patch.dict(
                os.environ,
                {
                    "EMACSCLIENT_PATH": str(fake_client),
                    "EMACS_EDIFF_APPROVAL": value,
                },
            )
            result = server.is_ediff_approval_enabled()
            assert result is True, f"Failed for value: {value}"

    def test_returns_false_when_emacsclient_not_found(
        self, mocker: MockerFixture
    ):
        """
        GIVEN: EMACS_EDIFF_APPROVAL=true but emacsclient not available
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns False and logs warning
        """
        mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": "true"})
        mocker.patch("shutil.which", return_value=None)

        result = server.is_ediff_approval_enabled()

        assert result is False


###############################################################################
# Tests for ensure_elisp_loaded
###############################################################################


class TestEnsureElispLoaded:
    """Tests for ensure_elisp_loaded function."""

    def test_loads_elisp_on_first_call(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: elisp file exists and has not been loaded
        WHEN: ensure_elisp_loaded() is called
        THEN: Calls emacsclient to load the file
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_client)})

        # Mock the elisp file existence check
        elisp_file = tmp_path / "emacs_ediff.el"
        elisp_file.write_text("(defun test ())")
        mocker.patch.object(
            Path, "__truediv__", return_value=elisp_file, autospec=False
        )

        mock_run = mocker.patch(
            "subprocess.run", return_value=MagicMock(returncode=0)
        )

        server.ensure_elisp_loaded()

        assert mock_run.called
        assert server.global_state.elisp_loaded is True

    def test_skips_loading_on_subsequent_calls(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: elisp has already been loaded
        WHEN: ensure_elisp_loaded() is called again
        THEN: Does not call emacsclient again
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_client)})

        server.global_state.elisp_loaded = True
        mock_run = mocker.patch("subprocess.run")

        server.ensure_elisp_loaded()

        mock_run.assert_not_called()

    def test_handles_missing_emacsclient(self, mocker: MockerFixture):
        """
        GIVEN: emacsclient is not available
        WHEN: ensure_elisp_loaded() is called
        THEN: Returns without error
        """
        mocker.patch.dict(os.environ, {}, clear=True)
        mocker.patch("shutil.which", return_value=None)

        server.ensure_elisp_loaded()

        assert server.global_state.elisp_loaded is False

    def test_handles_subprocess_error(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: emacsclient execution fails
        WHEN: ensure_elisp_loaded() is called
        THEN: Logs warning and continues
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(os.environ, {"EMACSCLIENT_PATH": str(fake_client)})

        # Mock elisp file
        elisp_file = tmp_path / "emacs_ediff.el"
        elisp_file.write_text("(defun test ())")
        mocker.patch.object(
            Path, "__truediv__", return_value=elisp_file, autospec=False
        )

        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "cmd"),
        )

        server.ensure_elisp_loaded()

        assert server.global_state.elisp_loaded is False


###############################################################################
# Tests for request_ediff_approval
###############################################################################


class TestRequestEdiffApproval:
    """Tests for request_ediff_approval function."""

    def test_auto_approves_when_disabled(self, mocker: MockerFixture):
        """
        GIVEN: ediff approval is disabled
        WHEN: request_ediff_approval() is called
        THEN: Returns (True, new_content) immediately
        """
        mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": "false"})

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "test-task"
        )

        assert approved is True
        assert final_content == new_content

    def test_returns_approved_when_user_approves(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: ediff enabled and user approves
        WHEN: request_ediff_approval() is called
        THEN: Returns (True, content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is True
        assert mock_run.called

    def test_returns_rejected_when_user_rejects(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: ediff enabled and user rejects
        WHEN: request_ediff_approval() is called
        THEN: Returns (False, original_content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"rejected"', returncode=0),
        )

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is False
        assert final_content == new_content

    def test_reads_edited_content_on_approval(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: user edits content before approving
        WHEN: request_ediff_approval() is called
        THEN: Returns edited content
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        # Mock subprocess to return approved
        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        # Mock the temp file read to return edited content
        original_read_text = Path.read_text

        def mock_read_text(self, *args, **kwargs):
            # If this is the new file being read after approval
            if "new-" in str(self):
                return "** TODO EDITED Task content"
            return original_read_text(self, *args, **kwargs)

        mocker.patch.object(Path, "read_text", mock_read_text)

        old_content = "** TODO Old task"
        new_content = "** TODO New task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is True
        assert final_content == "** TODO EDITED Task content"

    def test_handles_subprocess_timeout(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: subprocess times out
        WHEN: request_ediff_approval() is called
        THEN: Returns (False, original_content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("cmd", 300),
        )

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is False
        assert final_content == new_content

    def test_handles_subprocess_error(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: subprocess fails with error
        WHEN: request_ediff_approval() is called
        THEN: Falls back to auto-approve
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "cmd"),
        )

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is True
        assert final_content == new_content

    def test_uses_context_specific_filenames(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: context_name is provided
        WHEN: request_ediff_approval() is called
        THEN: Temp files use context-specific names
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old"
        new_content = "new"

        server.request_ediff_approval(old_content, new_content, "gh-127")

        # Check that emacsclient was called with paths containing context
        call_args = mock_run.call_args
        emacsclient_call = " ".join(call_args[0][0])
        assert "old-gh-127.org" in emacsclient_call
        assert "new-gh-127.org" in emacsclient_call

    def test_creates_temp_directory_with_prefix(
        self, tmp_path: Path, mocker: MockerFixture
    ):
        """
        GIVEN: ediff approval is requested
        WHEN: temp files are created
        THEN: TemporaryDirectory uses correct prefix
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        mocker.patch.dict(
            os.environ,
            {
                "EMACSCLIENT_PATH": str(fake_client),
                "EMACS_EDIFF_APPROVAL": "true",
            },
        )

        mock_tempdir = mocker.patch("tempfile.TemporaryDirectory")
        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        server.request_ediff_approval("old", "new", "test")

        mock_tempdir.assert_called_once_with(prefix="emacs-org-mcp-ediff-")

    def test_handles_missing_emacsclient(self, mocker: MockerFixture):
        """
        GIVEN: emacsclient is not found
        WHEN: request_ediff_approval() is called
        THEN: Falls back to auto-approve
        """
        mocker.patch.dict(os.environ, {"EMACS_EDIFF_APPROVAL": "true"})
        mocker.patch("shutil.which", return_value=None)

        old_content = "old"
        new_content = "new"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "test"
        )

        assert approved is True
        assert final_content == new_content
