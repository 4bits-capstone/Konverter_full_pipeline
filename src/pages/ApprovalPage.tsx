import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleCheck, RefreshCcw, TriangleAlert } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { approvalService } from "../services";
import { useKonverter, type ManualCheckKey } from "../state/KonverterContext";

export function ApprovalPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    activeDocument,
    activeDocumentId,
    pendingCount,
    reviewItems,
    metadata,
    metadataResolved,
    manualChecks,
    requiredManualChecks,
    toggleManualCheck,
    setAllManualChecks,
    resolveAllReviews,
    approvalReady,
    approvedAt,
    setApprovedAt,
    removeDocument,
    unlock,
    markDone,
    showToast,
  } = useKonverter();
  const [modalOpen, setModalOpen] = useState(false);
  const [approving, setApproving] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  const acceptedCount = reviewItems.filter(
    (item) => item.status === "accepted",
  ).length;
  const editedCount = reviewItems.filter(
    (item) => item.status === "edited",
  ).length;
  const removedCount = reviewItems.filter(
    (item) => item.status === "removed",
  ).length;
  const tableFlags = reviewItems.filter(
    (item) => item.type === "table" || item.type === "document_index",
  ).length;
  const pictureFlags = reviewItems.filter(
    (item) => item.type === "picture",
  ).length;
  const citationCount = metadata.citations
    .split(";")
    .filter((value) => value.trim()).length;

  const manualChecklist = useMemo(() => {
    const checklist: Array<{
      key: ManualCheckKey;
      title: string;
      sub: string;
    }> = [
      {
        key: "content",
        title: "Content verified against the source PDF",
        sub: `${acceptedCount} accepted · ${editedCount} edited · ${removedCount} removed from output`,
      },
    ];
    if (requiredManualChecks.includes("tables")) {
      checklist.push({
        key: "tables",
        title: "Flagged tables and figures checked",
        sub: `${tableFlags} table flag${tableFlags === 1 ? "" : "s"} · ${pictureFlags} picture flag${pictureFlags === 1 ? "" : "s"}`,
      });
    }
    if (requiredManualChecks.includes("citations")) {
      checklist.push({
        key: "citations",
        title: "Citations follow the required house style",
        sub: `${citationCount} citation${citationCount === 1 ? "" : "s"} recorded in the metadata`,
      });
    }
    return checklist;
  }, [
    acceptedCount,
    citationCount,
    editedCount,
    pictureFlags,
    removedCount,
    requiredManualChecks,
    tableFlags,
  ]);

  const reasons = useMemo(() => {
    const list: string[] = [];
    if (pendingCount)
      list.push(
        `${pendingCount} flagged item${pendingCount !== 1 ? "s" : ""} still pending`,
      );
    if (!metadataResolved)
      list.push(
        "the document metadata has not been confirmed on the metadata page",
      );
    const outstanding = requiredManualChecks.filter(
      (key) => !manualChecks[key],
    ).length;
    if (outstanding)
      list.push(
        `${outstanding} reviewer confirmation${outstanding !== 1 ? "s" : ""} outstanding`,
      );
    return list;
  }, [manualChecks, metadataResolved, pendingCount, requiredManualChecks]);

  const autoResolve = async () => {
    try {
      await resolveAllReviews();
      setAllManualChecks(true);
      showToast(
        metadataResolved
          ? "Review flags and reviewer confirmations resolved"
          : "Flags resolved · metadata still needs confirmation on the metadata page",
      );
    } catch (error) {
      showToast(
        error instanceof Error
          ? error.message
          : "Resolving the review flags failed",
      );
    }
  };

  const approve = async () => {
    if (approving) return;
    setApproving(true);
    try {
      const result = await approvalService.approve(
        activeDocumentId ?? undefined,
      );
      setApprovedAt(result.approvedAt);
      await queryClient.invalidateQueries({
        queryKey: ["publication", activeDocumentId],
      });
      unlock("preview");
      markDone("approval");
      setModalOpen(false);
      showToast("Document approved · output generated");
    } catch (error) {
      showToast(
        error instanceof Error
          ? error.message
          : "Approval failed. Check the backend and try again.",
      );
    } finally {
      setApproving(false);
    }
  };

  const openModal = () => {
    setModalOpen(true);
    window.setTimeout(() => confirmRef.current?.focus(), 0);
  };

  const revoke = async () => {
    if (revoking) return;
    setRevoking(true);
    try {
      if (activeDocumentId) await approvalService.revoke(activeDocumentId);
      setApprovedAt(null);
      await queryClient.invalidateQueries({
        queryKey: ["publication", activeDocumentId],
      });
      showToast("Approval revoked · generated output discarded");
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Revoking the approval failed",
      );
    } finally {
      setRevoking(false);
    }
  };

  const rejectAndReupload = () => {
    if (activeDocumentId) removeDocument(activeDocumentId);
    navigate("/upload");
    showToast(
      "Document removed from review. Add the corrected file to start again.",
    );
  };

  return (
    <section className="screen active" aria-labelledby="approval-heading">
      <div className="section-title">
        <span className="eyebrow">Stage 4 of 5</span>
        <h2 id="approval-heading" style={{ marginTop: 8 }}>
          Approve document
        </h2>
        <p className="lead">
          Final human sign-off. The document cannot generate published output
          until every required task is complete.
        </p>
      </div>

      {!approvedAt ? (
        <>
          {!approvalReady && (
            <div className="banner banner-warn" style={{ marginBottom: 20 }}>
              <TriangleAlert />
              <div>
                <b>Approval is blocked.</b> You still need to resolve:{" "}
                {reasons.join(", ")}.
              </div>
            </div>
          )}

          <div className="approve-grid">
            <div className="panel">
              <div className="panel-head">
                <h3>Approval checks</h3>
              </div>
              <div className="approval-check-sections">
                <section aria-labelledby="system-checks-heading">
                  <div className="approval-check-heading">
                    <div>
                      <span className="eyebrow">System checks</span>
                      <h4 id="system-checks-heading">Automated readiness</h4>
                    </div>
                    <span>Updated from review and metadata</span>
                  </div>
                  <ul className="checklist">
                    <li
                      className={`check ${pendingCount === 0 ? "ok" : "blocked"}`}
                    >
                      <div
                        className="checkbox"
                        role="checkbox"
                        aria-checked={pendingCount === 0}
                        aria-readonly="true"
                      >
                        <Check />
                      </div>
                      <div>
                        <div className="check-txt">
                          All flagged items reviewed
                        </div>
                        <div className="check-sub">
                          {pendingCount
                            ? `${pendingCount} of ${reviewItems.length} items still pending`
                            : `All ${reviewItems.length} items reviewed`}
                        </div>
                      </div>
                    </li>
                    <li
                      className={`check ${metadataResolved ? "ok" : "blocked"}`}
                    >
                      <div
                        className="checkbox"
                        role="checkbox"
                        aria-checked={metadataResolved}
                        aria-readonly="true"
                      >
                        <Check />
                      </div>
                      <div>
                        <div className="check-txt">Metadata confirmed</div>
                        <div className="check-sub">
                          {metadataResolved
                            ? "Confirmed on the metadata page"
                            : "Open the metadata page and select “Continue to approval” to confirm"}
                        </div>
                      </div>
                    </li>
                  </ul>
                </section>
                <section aria-labelledby="reviewer-checks-heading">
                  <div className="approval-check-heading">
                    <div>
                      <span className="eyebrow">Reviewer checks</span>
                      <h4 id="reviewer-checks-heading">Human confirmation</h4>
                    </div>
                    <span>
                      Only checks relevant to this document are listed
                    </span>
                  </div>
                  <ul className="checklist">
                    {manualChecklist.map((item) => (
                      <li
                        key={item.key}
                        className={`check ${manualChecks[item.key] ? "ok" : ""}`}
                      >
                        <button
                          type="button"
                          className="checkbox"
                          role="checkbox"
                          aria-checked={manualChecks[item.key]}
                          aria-label={item.title}
                          onClick={() => toggleManualCheck(item.key)}
                        >
                          <Check />
                        </button>
                        <div>
                          <div className="check-txt">{item.title}</div>
                          <div className="check-sub">{item.sub}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
              <div className="actionbar">
                <button
                  className="btn btn-seal"
                  disabled={!approvalReady}
                  onClick={openModal}
                >
                  <CircleCheck />
                  Approve document
                </button>
                <button
                  className="btn btn-outline"
                  onClick={() => navigate("/review")}
                >
                  Return to review
                </button>
                <div className="spacer" />
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ color: "var(--muted)" }}
                  onClick={autoResolve}
                >
                  Resolve all
                </button>
              </div>
            </div>

            <div className="panel panel-pad document-summary-card">
              <div className="field-label">Document summary</div>
              <ul className="summary-list">
                <li>
                  <span className="k">Document title</span>
                  <span className="v">
                    {activeDocument?.title ?? "No document selected"}
                  </span>
                </li>
                <li>
                  <span className="k">File name</span>
                  <span className="v mono full-file-name">
                    {activeDocument?.fileName ?? "Unavailable"}
                  </span>
                </li>
                <li>
                  <span className="k">Pages</span>
                  <span className="v mono">
                    {activeDocument?.pages || "Unavailable"}
                  </span>
                </li>
                <li>
                  <span className="k">Review status</span>
                  <span className="v">
                    <span
                      className={`status-tag ${pendingCount ? "pending" : "accepted"}`}
                    >
                      {pendingCount ? "In progress" : "Reviewed"}
                    </span>
                  </span>
                </li>
                <li>
                  <span className="k">Metadata status</span>
                  <span className="v">
                    <span
                      className={`status-tag ${metadataResolved ? "accepted" : "needs_attention"}`}
                    >
                      {metadataResolved ? "Confirmed" : "Not confirmed"}
                    </span>
                  </span>
                </li>
                <li>
                  <span className="k">Unresolved flags</span>
                  <span className="v mono">{pendingCount}</span>
                </li>
              </ul>
              <div className="reupload-action">
                <strong>Need to replace this document?</strong>
                <p>
                  This removes only the selected document and returns you to
                  upload. Other documents in the queue are kept.
                </p>
                <button
                  className="btn btn-danger"
                  type="button"
                  onClick={rejectAndReupload}
                >
                  <RefreshCcw />
                  Reject &amp; re-upload
                </button>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="panel approved-seal">
          <div className="seal-badge" aria-hidden="true">
            <CircleCheck />
          </div>
          <h2 style={{ fontSize: 24 }}>Document approved</h2>
          <p className="lead" style={{ margin: "8px auto 0" }}>
            Approved by <b>you</b> on{" "}
            <span className="mono">
              {new Date(approvedAt).toLocaleDateString("en-AU", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}{" "}
              {new Date(approvedAt).toLocaleTimeString("en-AU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
            . The accessible output can now be generated and exported.
          </p>
          <div
            style={{
              display: "flex",
              gap: 10,
              justifyContent: "center",
              marginTop: 22,
            }}
          >
            <button
              className="btn btn-primary"
              onClick={() => navigate("/preview")}
            >
              View landing page preview →
            </button>
            <button
              className="btn btn-outline"
              disabled={revoking}
              onClick={revoke}
            >
              {revoking ? "Revoking…" : "Revoke approval"}
            </button>
          </div>
        </div>
      )}

      {modalOpen && (
        <div
          className="overlay show"
          onMouseDown={(event) =>
            event.target === event.currentTarget &&
            !approving &&
            setModalOpen(false)
          }
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="approve-modal-title"
            onKeyDown={(event) =>
              event.key === "Escape" && !approving && setModalOpen(false)
            }
          >
            <div className="modal-ic">
              <CircleCheck />
            </div>
            <h3 id="approve-modal-title">Approve this document?</h3>
            <p>
              Once approved, Konverter generates the accessible HTML and JSON-LD
              output. Large documents can take a minute while every figure is
              rendered. This action is recorded in the audit trail against your
              account, and you can revoke approval before export.
            </p>
            <div className="modal-actions">
              <button
                className="btn btn-outline"
                disabled={approving}
                onClick={() => setModalOpen(false)}
              >
                Cancel
              </button>
              <button
                ref={confirmRef}
                className="btn btn-seal"
                disabled={approving}
                onClick={approve}
              >
                {approving ? "Generating output…" : "Yes, approve"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
