;;; emacs_archive.el --- Drive org-archive-subtree for the org MCP server -*- lexical-binding: t; -*-

;; Copyright (C) 2026

;; Author: Claude Code
;; Keywords: org-mode, archive

;;; Commentary:

;; One function, called over `emacsclient --eval' by the emacs-org-mcp
;; server: move the task carrying a given :CUSTOM_ID: out of tasks.org and
;; into wherever `org-archive-location' says archived subtrees go.
;;
;; Org already knows how to archive a subtree -- which file receives it, what
;; context to record alongside it, what level it arrives at.  None of that is
;; reimplemented here.  This locates the heading, hands off to
;; `org-archive-subtree', and reports which file the subtree went into.
;;
;; Deciding what to archive, checking that only the named task left, repairing
;; the links that pointed at it and committing the result are all the server's
;; job.  What is here runs with nobody at the keyboard, so it must never
;; prompt and never touch a buffer it was not asked about.

;;; Code:

(require 'org)
(require 'org-archive)

(defun org-mcp-archive--assert-unmodified (file)
  "Signal an error if a buffer visiting FILE holds unsaved changes.

Those edits are the user's, and only they can decide what becomes of them.
Refusing is the whole answer: this must not revert them, and the server
must not write the file underneath them."
  (let ((buffer (find-buffer-visiting file)))
    (when (and buffer (buffer-modified-p buffer))
      (error "Buffer %s has unsaved changes: save or revert it, then archive"
             (buffer-name buffer)))))

(defun org-mcp-archive-ready (file)
  "Report that FILE can be archived from, having changed nothing.

Signals exactly what `org-mcp-archive-subtree' would signal, so the server
can ask before it writes rather than after.  It has writing to do first: a
task with no :CUSTOM_ID: is given one, and writing that to a file Emacs
holds unsaved edits for means one of the two is lost -- the property when
the user saves their buffer over it, or their edits if they reload.

Returns t when the file is safe to touch."
  (org-mcp-archive--assert-unmodified file)
  t)

(defun org-mcp-archive--visit (file)
  "Return a buffer visiting FILE, in `org-mode', without ever prompting.

A buffer holding unsaved changes signals an error, as it does in
`org-mcp-archive-ready'; the check is repeated here because the buffer may
have been touched between the two calls.  A buffer whose file changed
underneath it is reverted first -- the server writes tasks.org between
Emacs' visits, and `find-file-noselect' would otherwise stop to ask about
the mismatch."
  (org-mcp-archive--assert-unmodified file)
  (let ((buffer (find-buffer-visiting file)))
    (when buffer
      (unless (verify-visited-file-modtime buffer)
        (with-current-buffer buffer
          (revert-buffer t t t))))
    (let ((buffer (or buffer (find-file-noselect file))))
      (with-current-buffer buffer
        (unless (derived-mode-p 'org-mode)
          (org-mode)))
      buffer)))

(defun org-mcp-archive--location ()
  "Return the file org would archive the subtree at point into.

The location has to be read at point rather than from `org-archive-location'
alone, since an `:ARCHIVE:' property on the subtree or any of its ancestors
overrides the global setting, as does a `#+ARCHIVE:' line in the file."
  (let ((location (or (org-entry-get nil "ARCHIVE" 'inherit)
                      org-archive-location)))
    (if (fboundp 'org-archive--compute-location)
        (car (org-archive--compute-location location))
      ;; Older org exposes no accessor for this, so read the setting the way
      ;; org documents it: the part before "::" names the file, `%s' stands
      ;; for the current file's name without its directory, and an empty
      ;; file part means this same file.
      (let* ((index (string-match "::" location))
             (spec (if (and index (> index 0))
                       (substring location 0 index)
                     ""))
             (name (file-name-nondirectory (buffer-file-name))))
        (if (string-empty-p spec)
            (buffer-file-name)
          (expand-file-name (format spec name)))))))

(defun org-mcp-archive-subtree (file custom-id)
  "Archive the subtree in FILE whose :CUSTOM_ID: property is CUSTOM-ID.

Returns the file the subtree was archived into, as a string, so the server
can verify the task arrived there.  Signals an error if the buffer has
unsaved changes or if no heading carries CUSTOM-ID.

FILE is widened before the search because `org-find-property' sees only the
accessible portion of the buffer, and a narrowed tasks.org would report a
task that is present as missing."
  (with-current-buffer (org-mcp-archive--visit file)
    (save-excursion
      (save-restriction
        (widen)
        (let ((position (org-find-property "CUSTOM_ID" custom-id)))
          (unless position
            (error "No heading in %s has :CUSTOM_ID: %s" file custom-id))
          (goto-char position)

          ;; Resolved while the heading still exists, since an :ARCHIVE:
          ;; property on it is part of the answer.
          (let ((archive (org-mcp-archive--location)))
            (org-archive-subtree)
            (save-buffer)

            ;; `org-archive-subtree' saves the archive buffer only when
            ;; `org-archive-subtree-save-file-p' says to, and the server
            ;; verifies the archive from disk.  Saving it here rather than
            ;; calling `org-save-all-org-buffers' keeps the user's other
            ;; modified org buffers out of it.
            (let ((buffer (find-buffer-visiting archive)))
              (when buffer
                (with-current-buffer buffer
                  (save-buffer))))

            archive))))))

(provide 'emacs_archive)
;;; emacs_archive.el ends here
