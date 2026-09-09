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

from mcp_server.config import Config, global_state
from mcp_server.utils import (
    ensure_elisp_loaded,
    get_emacsclient_path,
    is_ediff_approval_enabled,
    request_ediff_approval,
)

###############################################################################
# Fixtures
###############################################################################


@pytest.fixture(autouse=True)
def reset_elisp_loaded():
    """Forget which elisp files have been loaded, before and after each test."""
    global_state.elisp_loaded = set()
    yield
    global_state.elisp_loaded = set()


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
        config_factory: Callable[[Config], None],
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
            config_factory(Config(emacsclient_path=fake_client))
            expected: str | None = str(fake_client)
        else:
            fake_path = tmp_path / "nonexistent"
            config_factory(Config(emacsclient_path=fake_path))
            mocker.patch("shutil.which", return_value=which_return)
            expected = which_return

        result = get_emacsclient_path()

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
        config_factory: Callable[[Config], None],
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
                Config(
                    ediff_approval=ediff_approval, emacsclient_path=fake_client
                )
            )
        else:
            fake_path = tmp_path / "nonexistent"
            config_factory(
                Config(
                    ediff_approval=ediff_approval, emacsclient_path=fake_path
                )
            )
            mocker.patch("shutil.which", return_value=None)

        result = is_ediff_approval_enabled()

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
        config_factory: Callable[[Config], None],
    ):
        """
        GIVEN: elisp file exists and has not been loaded
        WHEN: ensure_elisp_loaded() is called
        THEN: Calls emacsclient to load the file
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(Config(emacsclient_path=fake_client))

        # Mock the elisp file existence check
        elisp_file = tmp_path / "emacs_ediff.el"
        elisp_file.write_text("(defun test ())")
        mocker.patch.object(
            Path, "__truediv__", return_value=elisp_file, autospec=False
        )

        mock_run = mocker.patch(
            "subprocess.run", return_value=MagicMock(returncode=0)
        )

        ensure_elisp_loaded()

        assert mock_run.called
        assert "emacs_ediff.el" in global_state.elisp_loaded

    def test_skips_loading_on_subsequent_calls(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
    ):
        """
        GIVEN: elisp has already been loaded
        WHEN: ensure_elisp_loaded() is called again
        THEN: Does not call emacsclient again
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(Config(emacsclient_path=fake_client))

        global_state.elisp_loaded = {"emacs_ediff.el"}
        mock_run = mocker.patch("subprocess.run")

        ensure_elisp_loaded()

        mock_run.assert_not_called()

    @pytest.mark.parametrize(
        "failure",
        ["no emacsclient", "emacsclient fails"],
    )
    def test_elisp_that_will_not_load_is_not_recorded_as_loaded(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
        failure: str,
    ):
        """
        GIVEN: An Emacs that cannot be reached, or one that refuses the load
         WHEN: The elisp is loaded
         THEN: It returns quietly, and nothing is recorded as loaded

        Both matter and for the same reason. Loading is skipped when the
        file is already recorded, so recording a load that did not happen
        means every later call skips it too -- one unreachable Emacs at
        startup would leave the elisp missing for the rest of the session.
        """
        if failure == "no emacsclient":
            mocker.patch("shutil.which", return_value=None)
            config_factory(Config(emacsclient_path=tmp_path / "nonexistent"))
        else:
            fake_client = tmp_path / "emacsclient"
            fake_client.write_text("fake")
            config_factory(Config(emacsclient_path=fake_client))

            elisp_file = tmp_path / "emacs_ediff.el"
            elisp_file.write_text("(defun test ())")
            mocker.patch.object(
                Path, "__truediv__", return_value=elisp_file, autospec=False
            )
            mocker.patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "cmd"),
            )

        ensure_elisp_loaded()

        assert global_state.elisp_loaded == set()


###############################################################################
# Tests for request_ediff_approval
###############################################################################


class TestRequestEdiffApproval:
    """Tests for request_ediff_approval function."""

    def test_auto_approves_when_disabled(
        self, config_factory: Callable[[Config], None]
    ):
        """
        GIVEN: ediff approval is disabled
        WHEN: request_ediff_approval() is called
        THEN: Returns (True, new_content) immediately
        """
        config_factory(Config(ediff_approval=False))

        old_content = "old task"
        new_content = "new task"

        approved, final_content = request_ediff_approval(
            old_content, new_content, "test-task"
        )

        assert approved is True
        assert final_content == new_content

    def test_returns_approved_when_user_approves(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
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
            Config(emacsclient_path=fake_client, ediff_approval=True)
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old task"
        new_content = "new task"

        approved, _ = request_ediff_approval(old_content, new_content, "gh-127")

        assert approved is True
        assert mock_run.called

    def test_returns_rejected_when_user_rejects(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
    ):
        """
        GIVEN: ediff enabled and user rejects
        WHEN: request_ediff_approval() is called
        THEN: Returns (False, original_content)
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            Config(emacsclient_path=fake_client, ediff_approval=True)
        )

        mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"rejected"', returncode=0),
        )

        old_content = "old task"
        new_content = "new task"

        approved, final_content = request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is False
        assert final_content == new_content

    def test_reads_edited_content_on_approval(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
    ):
        """
        GIVEN: user edits content before approving
        WHEN: request_ediff_approval() is called
        THEN: Returns edited content
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            Config(ediff_approval=True, emacsclient_path=fake_client)
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

        approved, final_content = request_ediff_approval(
            old_content, new_content, "gh-127"
        )

        assert approved is True
        assert final_content == "** TODO EDITED Task content"

    @pytest.mark.parametrize(
        "failure, reachable, approved",
        [
            pytest.param(
                subprocess.TimeoutExpired("cmd", 300),
                True,
                False,
                id="emacs-never-answered",
            ),
            pytest.param(
                subprocess.CalledProcessError(1, "cmd"),
                True,
                True,
                id="emacs-returned-an-error",
            ),
            pytest.param(None, False, True, id="no-emacsclient-at-all"),
        ],
    )
    def test_a_review_that_cannot_be_held_never_loses_the_content(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
        failure: Exception | None,
        reachable: bool,
        approved: bool,
    ):
        """
        GIVEN: An Emacs that never answers, one that returns an error, and no
               emacsclient at all
         WHEN: A change is put up for review
         THEN: The proposed content comes back unchanged in every case, since
               a review that could not be held is no reason to lose the edit
          AND: A missing or broken Emacs approves, because approval is a
               convenience and refusing would make the server unusable
               wherever Emacs is not running -- but a timeout does not, since
               there a person may still be looking at the diff, and approving
               under them applies a change they were in the middle of deciding
               about
        """
        if reachable:
            fake_client = tmp_path / "emacsclient"
            fake_client.write_text("fake")
            mocker.patch("subprocess.run", side_effect=failure)
        else:
            fake_client = tmp_path / "nonexistent"
            mocker.patch("shutil.which", return_value=None)

        config_factory(
            Config(ediff_approval=True, emacsclient_path=fake_client)
        )

        assert request_ediff_approval("old task", "new task", "gh-127") == (
            approved,
            "new task",
        )

    def test_uses_context_specific_filenames(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        config_factory: Callable[[Config], None],
    ):
        """
        GIVEN: context_name is provided
        WHEN: request_ediff_approval() is called
        THEN: Temp files use context-specific names
        """
        fake_client = tmp_path / "emacsclient"
        fake_client.write_text("fake")
        config_factory(
            Config(ediff_approval=True, emacsclient_path=fake_client)
        )

        mock_run = mocker.patch(
            "subprocess.run",
            return_value=MagicMock(stdout='"approved"', returncode=0),
        )

        old_content = "old"
        new_content = "new"

        request_ediff_approval(old_content, new_content, "gh-127")

        # Check that emacsclient was called with paths containing context
        #
        call_args = mock_run.call_args
        emacsclient_call = " ".join(call_args[0][0])
        assert "old-gh-127.org" in emacsclient_call
        assert "new-gh-127.org" in emacsclient_call
