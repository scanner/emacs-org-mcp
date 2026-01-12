#!/usr/bin/env python
#
"""
Tests for ediff approval functionality.

These tests mock subprocess.run to avoid requiring a running Emacs instance.
"""

import subprocess
from collections.abc import Callable
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

    @pytest.mark.parametrize(
        "config_path_exists,which_return,expected_type",
        [
            (True, None, "configured"),
            (False, "/usr/bin/emacsclient", "which"),
            (False, "/usr/local/bin/emacsclient", "which"),
            (False, None, "none"),
        ],
        ids=[
            "configured-path-exists",
            "config-missing-use-which",
            "default-missing-use-which",
            "not-found-anywhere",
        ],
    )
    def test_get_emacsclient_path(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
        config_path_exists: bool,
        which_return: str | None,
        expected_type: str,
    ):
        """
        GIVEN: various emacsclient path configurations
        WHEN: get_emacsclient_path() is called
        THEN: Returns correct path based on availability
        """
        if config_path_exists:
            fake_client = tmp_path / "my_emacsclient"
            fake_client.write_text("fake")
            config_factory(server.Config(emacsclient_path=fake_client))
            expected: str | None = str(fake_client)
        else:
            fake_path = tmp_path / "nonexistent"
            config_factory(server.Config(emacsclient_path=fake_path))
            mocker.patch("shutil.which", return_value=which_return)
            expected = which_return

        result = server.get_emacsclient_path()

        assert result == expected


###############################################################################
# Tests for is_ediff_approval_enabled
###############################################################################


class TestIsEdiffApprovalEnabled:
    """Tests for is_ediff_approval_enabled function."""

    @pytest.mark.parametrize(
        "ediff_approval,client_exists,expected",
        [
            (True, True, True),
            (False, True, False),
            (False, True, False),  # default (not explicitly set)
            (True, False, False),
        ],
        ids=[
            "enabled-client-available",
            "disabled",
            "not-set-defaults-false",
            "enabled-no-client",
        ],
    )
    def test_is_ediff_approval_enabled(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
        ediff_approval: bool,
        client_exists: bool,
        expected: bool,
    ):
        """
        GIVEN: various ediff_approval and emacsclient availability configurations
        WHEN: is_ediff_approval_enabled() is called
        THEN: Returns correct boolean based on both conditions
        """
        if client_exists:
            fake_client = tmp_path / "emacsclient"
            fake_client.write_text("fake")
            config_factory(
                server.Config(
                    ediff_approval=ediff_approval, emacsclient_path=fake_client
                )
            )
        else:
            fake_path = tmp_path / "nonexistent"
            config_factory(
                server.Config(
                    ediff_approval=ediff_approval, emacsclient_path=fake_path
                )
            )
            mocker.patch("shutil.which", return_value=None)

        result = server.is_ediff_approval_enabled()

        assert result is expected


###############################################################################
# Tests for ensure_elisp_loaded
###############################################################################


class TestEnsureElispLoaded:
    """Tests for ensure_elisp_loaded function."""

    def test_loads_elisp_on_first_call(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: elisp file exists and has not been loaded
        WHEN: ensure_elisp_loaded() is called
        THEN: Calls emacsclient to load the file
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(server.Config(emacsclient_path=fake_client))

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
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: elisp has already been loaded
        WHEN: ensure_elisp_loaded() is called again
        THEN: Does not call emacsclient again
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(server.Config(emacsclient_path=fake_client))

        server.global_state.elisp_loaded = True
        mock_run = mocker.patch("subprocess.run")

        server.ensure_elisp_loaded()

        mock_run.assert_not_called()

    def test_handles_missing_emacsclient(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: emacsclient is not available
        WHEN: ensure_elisp_loaded() is called
        THEN: Returns without error
        """
        fake_path = tmp_path / "nonexistent"
        mocker.patch("shutil.which", return_value=None)
        config_factory(server.Config(emacsclient_path=fake_path))

        server.ensure_elisp_loaded()

        assert server.global_state.elisp_loaded is False

    def test_handles_subprocess_error(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: emacsclient execution fails
        WHEN: ensure_elisp_loaded() is called
        THEN: Logs warning and continues
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(server.Config(emacsclient_path=fake_client))

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

    def test_auto_approves_when_disabled(
        self, config_factory: Callable[[server.Config], None]
    ):
        """
        GIVEN: ediff approval is disabled
        WHEN: request_ediff_approval() is called
        THEN: Returns (True, new_content) immediately
        """
        config_factory(server.Config(ediff_approval=False))

        old_content = "old task"
        new_content = "new task"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "test-task"
        )

        assert approved is True
        assert final_content == new_content

    def test_returns_approved_when_user_approves(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: ediff enabled and user approves
        WHEN: request_ediff_approval() is called
        THEN: Returns (True, content)
        """

        # We need a client that exists in order for the ediff process to be
        # run. Then we mock the `subprocess.run` command to say that it ran and
        # returned "approved"
        #
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(emacsclient_path=fake_client, ediff_approval=True)
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old task"
        new_content = "new task"

        approved, _ = server.request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is True
        assert mock_run.called

    def test_returns_rejected_when_user_rejects(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: ediff enabled and user rejects
        WHEN: request_ediff_approval() is called
        THEN: Returns (False, original_content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(emacsclient_path=fake_client, ediff_approval=True)
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
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: user edits content before approving
        WHEN: request_ediff_approval() is called
        THEN: Returns edited content
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_client)
        )

        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

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
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: subprocess times out
        WHEN: request_ediff_approval() is called
        THEN: Returns (False, original_content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_client)
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
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: subprocess fails with error
        WHEN: request_ediff_approval() is called
        THEN: Falls back to auto-approve
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_client)
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
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: context_name is provided
        WHEN: request_ediff_approval() is called
        THEN: Temp files use context-specific names
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_client)
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old"
        new_content = "new"

        server.request_ediff_approval(old_content, new_content, "gh-127")

        # Check that emacsclient was called with paths containing context
        #
        call_args = mock_run.call_args
        emacsclient_call = " ".join(call_args[0][0])
        assert "old-gh-127.org" in emacsclient_call
        assert "new-gh-127.org" in emacsclient_call

    def test_creates_temp_directory_with_prefix(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: ediff approval is requested
        WHEN: temp files are created
        THEN: TemporaryDirectory uses correct prefix
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_client)
        )

        mock_tempdir = mocker.patch("tempfile.TemporaryDirectory")
        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        server.request_ediff_approval("old", "new", "test")

        mock_tempdir.assert_called_once_with(prefix="emacs-org-mcp-ediff-")

    def test_handles_missing_emacsclient(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[server.Config], None],
    ):
        """
        GIVEN: emacsclient is not found
        WHEN: request_ediff_approval() is called
        THEN: Falls back to auto-approve
        """
        fake_path = tmp_path / "nonexistent"
        config_factory(
            server.Config(ediff_approval=True, emacsclient_path=fake_path)
        )
        mocker.patch("shutil.which", return_value=None)

        old_content = "old"
        new_content = "new"

        approved, final_content = server.request_ediff_approval(
            old_content, new_content, "test"
        )

        assert approved is True
        assert final_content == new_content
