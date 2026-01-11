;;; emacs_ediff.el --- Ediff-based approval for org-mcp operations -*- lexical-binding: t; -*-

;; Copyright (C) 2025

;; Author: Claude Code
;; Keywords: org-mode, ediff, approval

;;; Commentary:

;; This package provides an ediff-based approval mechanism for the
;; emacs-org-mcp server.  When enabled via EMACS_EDIFF_APPROVAL=true,
;; task and journal create/update operations present changes visually
;; in a new Emacs frame using ediff.
;;
;; User can:
;; - Review differences between old and new content side-by-side
;; - Edit the new content (buffer B) before approving
;; - Approve with C-c C-y (in control buffer)
;; - Reject with C-c C-k (in control buffer)
;; - Normal quit (q in control buffer) approves by default

;;; Code:

(require 'ediff)

(defvar org-mcp-ediff-decision nil
  "Decision variable for ediff approval workflow.")

(defvar org-mcp-ediff-frame nil
  "Frame created for ediff approval.")

(defun org-mcp-ediff-approve-action ()
  "Approve the ediff changes."
  (interactive)
  ;; Save buffer B (the new content)
  (when (and (boundp 'ediff-buffer-B)
             ediff-buffer-B
             (buffer-live-p ediff-buffer-B))
    (with-current-buffer ediff-buffer-B
      (save-buffer)))
  (setq org-mcp-ediff-decision 'approved)
  ;; Quit will trigger the quit hook which exits recursive edit
  (ediff-quit nil))

(defun org-mcp-ediff-reject-action ()
  "Reject the ediff changes."
  (interactive)
  (setq org-mcp-ediff-decision 'rejected)
  ;; Quit will trigger the quit hook which exits recursive edit
  (ediff-quit nil))

(defun org-mcp-ediff-setup-hook ()
  "Hook function to set up keybindings after ediff initializes.
This runs after ediff has set up its buffers."
  ;; Set keybindings only in control buffer
  (when (and (boundp 'ediff-control-buffer)
             ediff-control-buffer
             (buffer-live-p ediff-control-buffer))
    (with-current-buffer ediff-control-buffer
      (local-set-key (kbd "C-c C-y") 'org-mcp-ediff-approve-action)
      (local-set-key (kbd "C-c C-k") 'org-mcp-ediff-reject-action)

      ;; Add quit hook to handle all quit scenarios
      (add-hook 'ediff-quit-hook
                (lambda ()
                  ;; Default to approved if no explicit decision
                  (unless org-mcp-ediff-decision
                    (setq org-mcp-ediff-decision 'approved))
                  (org-mcp-ediff-cleanup)
                  ;; Exit recursive edit if we're in one
                  (when (> (recursion-depth) 0)
                    (exit-recursive-edit)))
                nil t)))

  ;; Display instructions
  (message "C-c C-y to APPROVE | C-c C-k to REJECT | q to quit (approves)."))

(defun org-mcp-ediff-cleanup ()
  "Clean up ediff buffers and frame after approval workflow."
  ;; Kill ediff buffers (check if bound and live)
  (when (and (boundp 'ediff-buffer-A)
             ediff-buffer-A
             (buffer-live-p ediff-buffer-A))
    (kill-buffer ediff-buffer-A))
  (when (and (boundp 'ediff-buffer-B)
             ediff-buffer-B
             (buffer-live-p ediff-buffer-B))
    (kill-buffer ediff-buffer-B))
  (when (and (boundp 'ediff-control-buffer)
             ediff-control-buffer
             (buffer-live-p ediff-control-buffer))
    (kill-buffer ediff-control-buffer))
  ;; Delete the frame if it still exists
  (when (and org-mcp-ediff-frame (frame-live-p org-mcp-ediff-frame))
    (delete-frame org-mcp-ediff-frame))
  (setq org-mcp-ediff-frame nil))

(defun org-mcp-ediff-approve (old-file new-file)
  "Present OLD-FILE vs NEW-FILE in ediff, wait for user decision.
User can edit NEW-FILE (buffer B) before approving.
Returns \"approved\" or \"rejected\" as a string."
  ;; Reset decision
  (setq org-mcp-ediff-decision nil)

  ;; Create a new frame for ediff
  (setq org-mcp-ediff-frame
        (make-frame '((name . "Org MCP Approval")
                     (width . 160)
                     (height . 50))))
  (select-frame org-mcp-ediff-frame)

  ;; Add our setup function to run after ediff initializes
  (add-hook 'ediff-startup-hook 'org-mcp-ediff-setup-hook)

  ;; Configure ediff for side-by-side layout in single frame
  (let ((ediff-window-setup-function 'ediff-setup-windows-plain)
        (ediff-split-window-function 'split-window-horizontally))
    ;; Start ediff on the files
    (ediff-files old-file new-file))

  ;; Remove our hook (only needed for this session)
  (remove-hook 'ediff-startup-hook 'org-mcp-ediff-setup-hook)

  ;; Enter recursive edit - this blocks until exit-recursive-edit is called
  (recursive-edit)

  ;; Return decision as string
  (if (eq org-mcp-ediff-decision 'approved) "approved" "rejected"))

(provide 'emacs_ediff)
;;; emacs_ediff.el ends here
