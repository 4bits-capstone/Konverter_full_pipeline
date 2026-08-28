import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleCheck,
  ExternalLink,
  Info,
  LoaderCircle,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { emptyMetadata } from "../config/workflow";
import { converterStagePath } from "../lib/converterRoutes";
import {
  approvalService,
  metadataService,
  publicationService,
} from "../services";
import { useKonverter } from "../state/KonverterContext";
import type { DocumentMetadata, MetadataFieldInfo } from "../types/konverter";

const metadataSchema = z.object({
  title: z.string().min(1, "Title is required."),
  publisher: z.string().min(1, "Publisher is required."),
  publishedDate: z.string().min(1, "Published date is required."),
  jurisdiction: z.string(),
  citations: z.string(),
});

type MetadataForm = z.infer<typeof metadataSchema>;
type MetadataField = keyof MetadataForm;
type MultipleField = "publisher" | "jurisdiction" | "citations";

interface FieldConfig {
  name: MetadataField;
  label: string;
  addLabel?: string;
  required?: boolean;
  multiple?: boolean;
  mono?: boolean;
  placeholder?: string;
  hint?: string;
}

const fields: FieldConfig[] = [
  { name: "title", label: "Title", required: true },
  { name: "publisher", label: "Publisher", required: true, multiple: true },
  {
    name: "publishedDate",
    label: "Published date",
    required: true,
    placeholder: "e.g. 14 December 2016",
  },
  { name: "jurisdiction", label: "Jurisdiction", multiple: true },
  {
    name: "citations",
    label: "Citations",
    addLabel: "citation",
    multiple: true,
    mono: true,
    hint: "Confirm legal citations follow the required house style.",
  },
];

const fieldOrder = fields.map((field) => field.name);
const multipleFields: MetadataField[] = [
  "publisher",
  "jurisdiction",
  "citations",
];
const isMultiple = (field: MetadataField): field is MultipleField =>
  multipleFields.includes(field);

const fallbackFieldInfo: Record<MetadataField, MetadataFieldInfo> = {
  title: {
    band: "low",
    score: 0,
    page: 1,
    evidence: "Confidence data is unavailable.",
    source: "Source unavailable",
  },
  publisher: {
    band: "low",
    score: 0,
    page: 1,
    evidence: "Confidence data is unavailable.",
    source: "Source unavailable",
  },
  publishedDate: {
    band: "low",
    score: 0,
    page: 1,
    evidence: "Confidence data is unavailable.",
    source: "Source unavailable",
  },
  jurisdiction: {
    band: "low",
    score: 0,
    page: 1,
    evidence: "Confidence data is unavailable.",
    source: "Source unavailable",
  },
  citations: {
    band: "low",
    score: 0,
    page: 1,
    evidence: "Confidence data is unavailable.",
    source: "Source unavailable",
  },
};

export function normaliseMetadataFields(
  incoming?: Partial<Record<string, MetadataFieldInfo>>,
): Record<MetadataField, MetadataFieldInfo> {
  return fieldOrder.reduce<Record<MetadataField, MetadataFieldInfo>>(
    (result, field) => {
      const legacyKey = field === "publishedDate" ? "published_date" : field;
      result[field] =
        incoming?.[field] ?? incoming?.[legacyKey] ?? fallbackFieldInfo[field];
      return result;
    },
    {} as Record<MetadataField, MetadataFieldInfo>,
  );
}

export function MetadataPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    activeDocument,
    activeDocumentId,
    metadata,
    setMetadata,
    metadataResolved,
    setMetadataResolved,
    pendingCount,
    reviewItems,
    setApprovedAt,
    unlock,
    markDone,
    showToast,
  } = useKonverter();
  const [editingFields, setEditingFields] = useState<Set<MetadataField>>(
    new Set(),
  );
  const [approvedFields, setApprovedFields] = useState<Set<MetadataField>>(
    new Set(),
  );
  const [activeEvidence, setActiveEvidence] =
    useState<MetadataField>("publishedDate");
  const [extraValues, setExtraValues] = useState<
    Record<MultipleField, string[]>
  >({ publisher: [], jurisdiction: [], citations: [] });
  const [snapshots, setSnapshots] = useState<
    Partial<Record<MetadataField, { value: string; extras: string[] }>>
  >({});
  const [evidenceFailed, setEvidenceFailed] = useState(false);
  const [approvalModalOpen, setApprovalModalOpen] = useState(false);
  const [approving, setApproving] = useState(false);
  const [pendingApprovalMetadata, setPendingApprovalMetadata] =
    useState<DocumentMetadata | null>(null);
  const approvalButtonRef = useRef<HTMLButtonElement | null>(null);

  const metadataQuery = useQuery({
    queryKey: ["metadata", activeDocumentId ?? "none"],
    queryFn: () => metadataService.get(activeDocumentId!),
    enabled: Boolean(activeDocumentId),
  });
  const extractedMetadata = metadataQuery.data?.metadata ?? metadata;
  const fieldInfo = useMemo(
    () => normaliseMetadataFields(metadataQuery.data?.fields),
    [metadataQuery.data?.fields],
  );

  const {
    register,
    handleSubmit,
    reset,
    resetField,
    watch,
    getValues,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<MetadataForm>({
    resolver: zodResolver(metadataSchema),
    defaultValues: extractedMetadata,
  });

  useEffect(() => {
    if (!metadataQuery.data) return;
    setMetadata(metadataQuery.data.metadata);
    reset(metadataQuery.data.metadata);
    setApprovedFields(new Set());
    setExtraValues({ publisher: [], jurisdiction: [], citations: [] });
  }, [metadataQuery.data, reset, setMetadata]);

  const publishedDate = watch("publishedDate");

  const onSubmit = async (values: MetadataForm) => {
    const withMultipleValues: DocumentMetadata = {
      ...values,
      publisher: [values.publisher, ...extraValues.publisher]
        .filter((value) => value.trim())
        .join("; "),
      jurisdiction: [values.jurisdiction, ...extraValues.jurisdiction]
        .filter((value) => value.trim())
        .join("; "),
      citations: [values.citations, ...extraValues.citations]
        .filter((value) => value.trim())
        .join("; "),
    };
    const saved = await metadataService.save(
      withMultipleValues,
      activeDocumentId ?? undefined,
    );
    setMetadata(saved);
    setMetadataResolved(true);
    markDone("metadata");
    markDone("review");
    setPendingApprovalMetadata(saved);
    setApprovalModalOpen(true);
    window.setTimeout(() => approvalButtonRef.current?.focus(), 0);
    showToast("Metadata confirmed · final system checks ready");
  };

  const approvalMetadata = pendingApprovalMetadata ?? metadata;
  const requiredMetadataComplete = Boolean(
    approvalMetadata.title.trim() &&
    approvalMetadata.publisher.trim() &&
    approvalMetadata.publishedDate.trim(),
  );
  const approvalChecks = [
    {
      label: "Document identified",
      ok: Boolean(activeDocument && approvalMetadata.title.trim()),
      detail:
        approvalMetadata.title.trim() ||
        activeDocument?.title ||
        "No document title available",
    },
    {
      label: "Review flags resolved",
      ok: pendingCount === 0,
      detail: pendingCount
        ? `${pendingCount} of ${reviewItems.length} flags still need a decision`
        : `All ${reviewItems.length} flags have a decision`,
    },
    {
      label: "Metadata confirmed",
      ok: requiredMetadataComplete,
      detail: requiredMetadataComplete
        ? `${approvalMetadata.publisher} · ${approvalMetadata.publishedDate}`
        : "Title, publisher or published date is missing",
    },
    {
      label: "Accessible output ready",
      ok: pendingCount === 0 && requiredMetadataComplete,
      detail:
        "Accessible HTML, landing page, structured JSON and embedded JSON-LD will be generated",
    },
  ];
  const approvalReady = approvalChecks.every((check) => check.ok);

  const approveAndOpenPreview = async () => {
    if (!approvalReady || approving) return;
    setApproving(true);
    try {
      const result = await approvalService.approve(
        activeDocumentId ?? undefined,
      );
      setApprovedAt(result.approvedAt);
      await queryClient.invalidateQueries({
        queryKey: ["publication", activeDocumentId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["report-html", activeDocumentId],
      });
      unlock("preview");
      markDone("approval");
      setApprovalModalOpen(false);
      showToast("Document approved · accessible output generated");
      navigate(converterStagePath("preview"));
    } catch (error) {
      showToast(
        error instanceof Error ? error.message : "Approval failed. Try again.",
      );
    } finally {
      setApproving(false);
    }
  };

  const setEditing = (field: MetadataField, editing: boolean) => {
    setEditingFields((current) => {
      const next = new Set(current);
      if (editing) next.add(field);
      else next.delete(field);
      return next;
    });
  };

  const startEditing = (field: MetadataField) => {
    setActiveEvidence(field);
    setSnapshots((current) => ({
      ...current,
      [field]: {
        value: getValues(field),
        extras: isMultiple(field) ? [...extraValues[field]] : [],
      },
    }));
    setEditing(field, true);
  };

  const cancelEditing = (field: MetadataField) => {
    const snapshot = snapshots[field];
    if (snapshot) {
      setValue(field, snapshot.value, { shouldValidate: true });
      if (isMultiple(field))
        setExtraValues((current) => ({ ...current, [field]: snapshot.extras }));
    }
    setEditing(field, false);
  };

  const saveField = (field: MetadataField, label: string) => {
    setEditing(field, false);
    setApprovedFields((current) => new Set(current).add(field));
    showToast(`${label} saved`);
  };

  const approveField = (field: MetadataField, label: string) => {
    setActiveEvidence(field);
    setApprovedFields((current) => new Set(current).add(field));
    showToast(`${label} approved`);
  };

  const resetSuggestion = (field: MetadataField) => {
    resetField(field, {
      defaultValue: extractedMetadata[field] ?? emptyMetadata[field],
    });
    if (isMultiple(field))
      setExtraValues((current) => ({ ...current, [field]: [] }));
    setMetadataResolved(false);
    setApprovedFields((current) => {
      const next = new Set(current);
      next.delete(field);
      return next;
    });
    showToast(
      `${fields.find((config) => config.name === field)?.label ?? field} reset to the rule-based suggestion`,
    );
  };

  const addValue = (field: MultipleField) => {
    setExtraValues((current) => ({
      ...current,
      [field]: [...current[field], ""],
    }));
  };

  const updateExtraValue = (
    field: MultipleField,
    index: number,
    value: string,
  ) => {
    setExtraValues((current) => ({
      ...current,
      [field]: current[field].map((entry, entryIndex) =>
        entryIndex === index ? value : entry,
      ),
    }));
  };

  const removeExtraValue = (field: MultipleField, index: number) => {
    setExtraValues((current) => ({
      ...current,
      [field]: current[field].filter((_, entryIndex) => entryIndex !== index),
    }));
  };

  const hasError = (field: MetadataField) =>
    Boolean(errors[field]) || (field === "publishedDate" && !publishedDate);
  const fieldsNeedingReview = fieldOrder.filter(
    (field) =>
      hasError(field) ||
      (fieldInfo[field].band !== "high" && !approvedFields.has(field)),
  );
  const reviewCount = fieldsNeedingReview.length;
  const evidence = fieldInfo[activeEvidence];
  const evidenceLabel =
    fields.find((field) => field.name === activeEvidence)?.label ??
    activeEvidence;
  const evidencePageUrl = publicationService.sourceUrl(
    activeDocumentId ?? "",
    evidence.page,
  );
  const evidenceImageUrl = publicationService.metadataEvidenceUrl(
    activeDocumentId ?? "",
    activeEvidence,
  );

  useEffect(() => {
    setEvidenceFailed(false);
  }, [activeDocumentId, activeEvidence, evidence.page]);

  const renderField = (config: FieldConfig) => {
    const {
      name,
      label,
      addLabel,
      required,
      multiple,
      mono,
      placeholder,
      hint,
    } = config;
    const extraLabel = addLabel ?? label.toLowerCase();
    const editing = editingFields.has(name);
    const approved = approvedFields.has(name);
    const { band, score } = fieldInfo[name];
    const error = hasError(name);
    const tone = error
      ? "alert"
      : approved || band === "high"
        ? "ok"
        : band === "low"
          ? "alert"
          : "warn";

    return (
      <div
        key={name}
        className={`metadata-field is-${tone} ${editing ? "editing" : ""}`}
        role="listitem"
        onFocus={() => setActiveEvidence(name)}
      >
        <div className="metadata-field-head">
          <label htmlFor={`metadata-${name}`}>
            {label}
            {required && (
              <span className="req" aria-label="required">
                *
              </span>
            )}
            <ConfidenceBadge
              band={error ? "low" : band}
              score={score}
              size="lg"
            />
          </label>
          <div className="metadata-field-actions">
            {!editing && !error && fieldsNeedingReview.includes(name) && (
              <button
                className="btn btn-approve btn-sm"
                type="button"
                onClick={() => approveField(name, label)}
              >
                <Check />
                Approve
              </button>
            )}
            <button
              className="btn btn-outline btn-sm"
              type="button"
              onClick={() =>
                editing ? cancelEditing(name) : startEditing(name)
              }
            >
              <Pencil />
              Edit
            </button>
          </div>
        </div>

        {editing ? (
          <>
            <input
              id={`metadata-${name}`}
              className={`input ${mono ? "mono" : ""} ${errors[name] ? "err" : ""}`}
              placeholder={placeholder}
              {...register(name)}
            />
            {multiple &&
              extraValues[name as MultipleField].map((value, index) => (
                <div className="multiple-value-row" key={`${name}-${index}`}>
                  <input
                    className={`input ${mono ? "mono" : ""}`}
                    aria-label={`Additional ${extraLabel} ${index + 2}`}
                    value={value}
                    onChange={(event) =>
                      updateExtraValue(
                        name as MultipleField,
                        index,
                        event.target.value,
                      )
                    }
                  />
                  <button
                    className="btn btn-ghost btn-sm"
                    type="button"
                    aria-label={`Remove additional ${extraLabel} ${index + 2}`}
                    onClick={() =>
                      removeExtraValue(name as MultipleField, index)
                    }
                  >
                    <Trash2 />
                  </button>
                </div>
              ))}
            {errors[name] && (
              <div className="err-msg show">
                <TriangleAlert />
                {errors[name]?.message}
              </div>
            )}
            {hint && <div className="hint">{hint}</div>}
            {multiple && (
              <button
                className="btn btn-ghost btn-sm field-add"
                type="button"
                onClick={() => addValue(name as MultipleField)}
              >
                <Plus />
                Add another
              </button>
            )}
            <div className="metadata-field-foot">
              <button
                className="btn btn-primary btn-sm"
                type="button"
                onClick={() => saveField(name, label)}
              >
                <Save />
                Save
              </button>
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                onClick={() => cancelEditing(name)}
              >
                Cancel
              </button>
              <button
                className="btn btn-ghost btn-sm"
                type="button"
                onClick={() => resetSuggestion(name)}
              >
                <RotateCcw />
                Reset to rule suggestion
              </button>
            </div>
          </>
        ) : (
          <>
            <div
              className={`field-value ${mono ? "mono" : ""}`}
              id={`metadata-${name}`}
            >
              {[
                getValues(name),
                ...(multiple ? extraValues[name as MultipleField] : []),
              ]
                .filter((value) => value.trim())
                .join(" · ") || (
                <span className="field-value-empty">Not set</span>
              )}
            </div>
            {error && (
              <div className="err-msg show">
                <TriangleAlert />
                {errors[name]?.message ??
                  "A value is required. Select Edit to enter it."}
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  return (
    <section className="screen active" aria-labelledby="metadata-heading">
      <div className="section-title metadata-titlebar">
        <div>
          <span className="eyebrow">Stage 3 of 4</span>
          <h2 id="metadata-heading">Review metadata</h2>
          <p className="lead">
            Confirm the source details people will use to identify and cite this
            report.
          </p>
        </div>
        <span
          className={`pill ${reviewCount ? "warn" : "ok"}`}
          aria-live="polite"
        >
          {reviewCount ? <TriangleAlert /> : <Check />}
          {reviewCount ? (
            <span>
              <b className="pill-count">{reviewCount}</b>{" "}
              <span className="pill-label">
                {reviewCount === 1 ? "field needs" : "fields need"} review
              </span>
            </span>
          ) : (
            <span className="pill-label">
              {metadataResolved ? "Metadata confirmed" : "All fields reviewed"}
            </span>
          )}
        </span>
      </div>

      {metadataQuery.isLoading ? (
        <div className="panel panel-pad workflow-loading" role="status">
          <LoaderCircle className="spinner-icon" />
          Loading rule-based metadata and evidence…
        </div>
      ) : metadataQuery.isError ? (
        <div className="banner banner-warn">
          <TriangleAlert />
          <div>
            Metadata could not be loaded. Return to upload and confirm
            processing completed successfully.
          </div>
        </div>
      ) : (
        <div className="meta-grid">
          <form className="panel" onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="panel-head">
              <h3>Document metadata</h3>
              <span className="panel-head-note">
                Select Edit to change a field
              </span>
            </div>
            <div className="panel-pad metadata-fields">
              <div
                className="metadata-field-list"
                role="list"
                aria-label="Metadata review fields"
              >
                {fields.map(renderField)}
              </div>
              <div className="metadata-form-actions">
                <button
                  className="btn btn-primary"
                  type="submit"
                  disabled={isSubmitting || reviewCount > 0}
                >
                  {isSubmitting
                    ? "Saving…"
                    : reviewCount > 0
                      ? `Resolve ${reviewCount} field${reviewCount === 1 ? "" : "s"} to continue`
                      : "Run final system checks →"}
                </button>
                <button
                  className="btn btn-outline"
                  type="button"
                  onClick={() => navigate(converterStagePath("review"))}
                >
                  Return to review
                </button>
              </div>
            </div>
          </form>

          <aside className="metadata-evidence-column" aria-live="polite">
            <div className="panel panel-pad">
              <div className="metadata-evidence-heading">
                <div className="field-label">{evidenceLabel} evidence</div>
                <a
                  className="source-page-link"
                  href={evidencePageUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open original page <ExternalLink aria-hidden="true" />
                </a>
              </div>
              <div className="evidence">
                {evidence.evidence}
                <span className="src">↳ {evidence.source}</span>
              </div>
              <div className="page-doc metadata-page-preview source-evidence-preview">
                {!evidenceFailed ? (
                  <img
                    src={evidenceImageUrl}
                    alt={`Original PDF page ${evidence.page} containing ${evidenceLabel.toLowerCase()} evidence`}
                    loading="lazy"
                    onError={() => setEvidenceFailed(true)}
                  />
                ) : (
                  <div className="source-evidence-fallback">
                    <TriangleAlert aria-hidden="true" />
                    <span>
                      The original-page screenshot is unavailable. Open the PDF
                      page to verify this field.
                    </span>
                  </div>
                )}
              </div>
            </div>
            <div className="banner banner-info">
              <Info />
              <div>
                Metadata rules inspect Docling text from pages 1–8. Low or
                medium confidence fields require a close check.
              </div>
            </div>
          </aside>
        </div>
      )}

      {approvalModalOpen ? (
        <div
          className="overlay show"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !approving)
              setApprovalModalOpen(false);
          }}
        >
          <section
            className="modal approval-popup"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-approval-heading"
            aria-describedby="approval-popup-description"
          >
            <div className="approval-popup-header">
              <div className="modal-ic"><CircleCheck aria-hidden="true" /></div>
              <div>
                <span className="eyebrow">Final system checks</span>
                <h3 id="confirm-approval-heading">
                  Approve {approvalMetadata.title || "this document"}?
                </h3>
              </div>
            </div>
            <p className="approval-popup-intro" id="approval-popup-description">
              Review the completed checks, then approve this document to generate
              its accessible outputs.
            </p>
            <ul className="checklist" aria-label="Approval system checks">
              {approvalChecks.map((check) => (
                <li
                  className={`check ${check.ok ? "ok" : "blocked"}`}
                  key={check.label}
                >
                  <span
                    className="checkbox"
                    role="img"
                    aria-label={check.ok ? "Passed" : "Blocked"}
                  >
                    {check.ok ? <Check aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
                  </span>
                  <div>
                    <div className="check-txt">{check.label}</div>
                    <div className="check-sub">{check.detail}</div>
                  </div>
                </li>
              ))}
            </ul>
            <div
              className="approval-popup-summary"
              aria-label="Document approval summary"
            >
              <span>
                <b>File</b>
                {activeDocument?.fileName || "Not available"}
              </span>
              <span>
                <b>Review flags</b>
                {reviewItems.length - pendingCount}/{reviewItems.length}{" "}
                resolved
              </span>
              <span>
                <b>Metadata</b>
                {requiredMetadataComplete ? "Confirmed" : "Incomplete"}
              </span>
            </div>
            <div className="modal-actions">
              <button
                className="btn btn-outline"
                type="button"
                disabled={approving}
                onClick={() => setApprovalModalOpen(false)}
              >
                Cancel
              </button>
              <button
                ref={approvalButtonRef}
                className="btn btn-primary"
                type="button"
                disabled={!approvalReady || approving}
                onClick={approveAndOpenPreview}
              >
                {approving ? "Generating outputs…" : "Approve and open preview"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
