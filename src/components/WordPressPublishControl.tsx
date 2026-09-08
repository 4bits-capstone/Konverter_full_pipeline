import { Check, Eye, FileCheck2, Globe, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { publicationService } from "../services";
import type { WordPressPublication } from "../types/konverter";

type PublishStatus = WordPressPublication["status"];

function PublishDialog({
  hasDraft,
  onClose,
  onConfirm,
}: {
  hasDraft: boolean;
  onClose: () => void;
  onConfirm: (status: PublishStatus) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [choice, setChoice] = useState<PublishStatus>(
    hasDraft ? "publish" : "draft",
  );
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current!;
    node.showModal();
    node.querySelector<HTMLInputElement>("input:checked")?.focus();
    return () => {
      node.close();
      previous?.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="wordpress-publish-dialog"
      aria-labelledby="wordpress-dialog-title"
      aria-describedby="wordpress-dialog-description"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="wordpress-dialog-content">
        <div className="wordpress-dialog-heading">
          <span className="eyebrow">WordPress staging</span>
          <button
            className="wordpress-dialog-close"
            type="button"
            aria-label="Close publishing options"
            onClick={onClose}
          >
            <X aria-hidden="true" />
          </button>
        </div>
        <h3 id="wordpress-dialog-title">
          {hasDraft ? "Ready to publish live?" : "Publish to WordPress"}
        </h3>
        <p id="wordpress-dialog-description">
          {hasDraft
            ? "Your saved draft will remain in WordPress. This creates one separate live page from the approved document."
            : "Choose how to share your approved document on the staging site."}
        </p>
        <fieldset className="wordpress-publish-choices">
          <legend className="sr-only">Publication visibility</legend>
          {!hasDraft && (
            <label className={choice === "draft" ? "is-selected" : ""}>
              <input
                type="radio"
                name="wordpress-visibility"
                value="draft"
                checked={choice === "draft"}
                onChange={() => setChoice("draft")}
              />
              <FileCheck2 aria-hidden="true" />
              <span>
                <strong>Save draft</strong>
                <small>
                  Review privately in WordPress. You can publish live later.
                </small>
              </span>
            </label>
          )}
          <label className={choice === "publish" ? "is-selected" : ""}>
            <input
              type="radio"
              name="wordpress-visibility"
              value="publish"
              checked={choice === "publish"}
              onChange={() => setChoice("publish")}
            />
            <Globe aria-hidden="true" />
            <span>
              <strong>Publish live</strong>
              <small>
                {hasDraft
                  ? "Publish live on the staging site. Draft publishing will no longer be offered."
                  : "Publish live on the staging site, available to visitors immediately."}
              </small>
            </span>
          </label>
        </fieldset>
        <div className="wordpress-dialog-actions">
          <button className="btn btn-outline" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => onConfirm(choice)}
          >
            {choice === "draft" ? "Save draft" : "Publish live"}
          </button>
        </div>
      </div>
    </dialog>
  );
}

export function WordPressPublishControl({
  documentId,
  onPublished,
}: {
  documentId: string;
  onPublished: (status: PublishStatus) => void;
}) {
  const client = useQueryClient();
  const queryKey = ["wordpress-publication", documentId];
  const [dialogOpen, setDialogOpen] = useState(false);
  const submitting = useRef(false);
  const status = useQuery({
    queryKey,
    queryFn: () => publicationService.getWordPressPublication(documentId),
    retry: false,
  });
  const publish = useMutation({
    mutationFn: (choice: PublishStatus) =>
      publicationService.publishToWordPress(documentId, choice),
    retry: false,
    onSuccess: (result) => {
      client.setQueryData(queryKey, result);
      onPublished(result.status);
    },
    onSettled: async () => {
      await status.refetch();
      submitting.current = false;
    },
  });
  const result = status.data ?? publish.data;
  const busy = publish.isPending;
  const disabled =
    busy || status.isPending || status.isFetching || status.isError;
  const live = result?.status === "publish";

  const confirm = (choice: PublishStatus) => {
    if (submitting.current || disabled || live) return;
    submitting.current = true;
    setDialogOpen(false);
    publish.mutate(choice);
  };

  return (
    <div
      className={`wordpress-publish-control${result ? " wordpress-publish-success" : ""}`}
    >
      {result && (
        <a
          className="btn btn-primary wordpress-view-button"
          href={result.previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={
            live
              ? "Open the live WordPress page"
              : "View the WordPress draft. Sign-in is required."
          }
        >
          <Eye aria-hidden="true" />
          {live ? "View live page" : "View draft"}
        </a>
      )}
      {!live && (
        <button
          type="button"
          className={`btn ${result ? "btn-outline" : "btn-primary"} wordpress-publish-button`}
          disabled={disabled}
          onClick={() => {
            publish.reset();
            setDialogOpen(true);
          }}
        >
          {busy ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Publishing…
            </>
          ) : (
            <>
              <Send aria-hidden="true" />
              {result ? "Publish live" : "Publish to WordPress"}
            </>
          )}
        </button>
      )}
      {result && !busy && (
        <span className="wordpress-publish-meta" role="status">
          <Check aria-hidden="true" />
          {live ? "Live on WordPress" : "Draft saved · not live"}
        </span>
      )}
      {!result && !busy && !status.isError && (
        <span className="wordpress-publish-meta">
          Save a draft or publish live
        </span>
      )}
      {busy && (
        <span className="wordpress-publish-meta" role="status">
          Sending your document to WordPress…
        </span>
      )}
      {status.isError && (
        <p className="wordpress-publish-error" role="alert">
          Could not load WordPress publishing status.
        </p>
      )}
      {publish.isError && result?.status !== publish.variables && (
        <p className="wordpress-publish-error" role="alert">
          {publish.error instanceof Error
            ? publish.error.message
            : "Publishing could not be confirmed."}
        </p>
      )}
      {status.isError && (
        <button
          type="button"
          className="wordpress-status-retry"
          disabled={status.isFetching}
          onClick={() => void status.refetch()}
        >
          Check status again
        </button>
      )}
      {dialogOpen && !busy && !status.isError && !live && (
        <PublishDialog
          hasDraft={Boolean(result)}
          onClose={() => setDialogOpen(false)}
          onConfirm={confirm}
        />
      )}
    </div>
  );
}
