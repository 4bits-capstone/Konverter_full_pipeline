import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { emptyMetadata, processingSteps } from "../config/workflow";
import { documentService, reviewService } from "../services";
import type {
  DocumentMetadata,
  DocumentProcessingJob,
  DocumentSummary,
  ReviewItem,
  ReviewStatus,
  ReviewTableData,
  ReviewType,
  ReviewUpdate,
  Stage,
} from "../types/konverter";

export type ManualCheckKey = "content" | "tables" | "citations";

type ToastState = { message: string; id: number } | null;

interface DocumentWorkflow {
  metadataResolved: boolean;
  approvedAt: string | null;
  manualChecks: Record<ManualCheckKey, boolean>;
}

const emptyWorkflow = (): DocumentWorkflow => ({
  metadataResolved: false,
  approvedAt: null,
  manualChecks: { content: false, tables: false, citations: false },
});

interface KonverterContextValue {
  documents: DocumentSummary[];
  activeDocument: DocumentSummary | null;
  activeDocumentId: string | null;
  addDocuments: (documents: DocumentSummary[]) => void;
  removeDocument: (id: string) => void;
  selectDocument: (id: string) => void;
  documentProcessing: Record<string, DocumentProcessingJob>;
  completedDocuments: DocumentSummary[];
  runningDocuments: DocumentSummary[];
  startDocumentProcessing: (id: string) => void;
  stopDocumentProcessing: (id: string) => void;
  uploaded: boolean;
  setUploaded: (value: boolean) => void;
  metadata: DocumentMetadata;
  setMetadata: (metadata: DocumentMetadata) => void;
  metadataResolved: boolean;
  setMetadataResolved: (value: boolean) => void;
  approvedAt: string | null;
  setApprovedAt: (value: string | null) => void;
  unlocked: Record<Stage, boolean>;
  unlock: (stage: Stage) => void;
  doneStages: Set<Stage>;
  markDone: (stage: Stage) => void;
  reviewItems: ReviewItem[];
  reviewLoading: boolean;
  setReviewStatus: (id: string, status: ReviewStatus) => Promise<ReviewItem>;
  updateReviewText: (id: string, text: string) => Promise<void>;
  updateReviewTable: (id: string, table: ReviewTableData) => Promise<void>;
  updateReviewLabel: (
    id: string,
    type: ReviewType,
    label: string,
  ) => Promise<void>;
  saveReviewItem: (id: string, changes: ReviewUpdate) => Promise<ReviewItem>;
  bulkUpdateReviewItems: (
    ids: string[],
    changes: ReviewUpdate,
  ) => Promise<ReviewItem[]>;
  resolveAllReviews: () => Promise<void>;
  pendingCount: number;
  resolvedCount: number;
  manualChecks: Record<ManualCheckKey, boolean>;
  requiredManualChecks: ManualCheckKey[];
  toggleManualCheck: (key: ManualCheckKey) => void;
  setAllManualChecks: (value: boolean) => void;
  approvalReady: boolean;
  toastState: ToastState;
  showToast: (message: string) => void;
  resetWorkflow: () => void;
}

const KonverterContext = createContext<KonverterContextValue | null>(null);

const initialUnlocked: Record<Stage, boolean> = {
  upload: true,
  review: false,
  metadata: false,
  approval: false,
  preview: false,
};

export function KonverterProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const [documentProcessing, setDocumentProcessing] = useState<
    Record<string, DocumentProcessingJob>
  >({});
  const [workflowByDocument, setWorkflowByDocument] = useState<
    Record<string, DocumentWorkflow>
  >({});
  const [uploaded, setUploaded] = useState(false);
  const [metadata, setMetadataState] =
    useState<DocumentMetadata>(emptyMetadata);
  const [unlocked, setUnlocked] = useState(initialUnlocked);
  const [doneStages, setDoneStages] = useState<Set<Stage>>(new Set());
  const [toastState, setToastState] = useState<ToastState>(null);
  const reviewQueryKey = useMemo(
    () => ["review-items", activeDocumentId ?? "none"] as const,
    [activeDocumentId],
  );

  const activeWorkflow =
    (activeDocumentId && workflowByDocument[activeDocumentId]) ||
    emptyWorkflow();
  const { metadataResolved, approvedAt, manualChecks } = activeWorkflow;

  const { data: reviewItems = [], isLoading: reviewLoading } = useQuery({
    queryKey: reviewQueryKey,
    queryFn: () => reviewService.getReviewItems(activeDocumentId ?? undefined),
    enabled: Boolean(
      activeDocumentId &&
      documentProcessing[activeDocumentId]?.state === "complete",
    ),
  });

  const patchWorkflow = useCallback(
    (id: string | null, changes: Partial<DocumentWorkflow>) => {
      if (!id) return;
      setWorkflowByDocument((current) => ({
        ...current,
        [id]: { ...(current[id] ?? emptyWorkflow()), ...changes },
      }));
    },
    [],
  );

  const unlock = useCallback((stage: Stage) => {
    setUnlocked((current) => ({ ...current, [stage]: true }));
  }, []);

  const markDone = useCallback((stage: Stage) => {
    setDoneStages((current) => new Set(current).add(stage));
  }, []);

  const showToast = useCallback((message: string) => {
    setToastState({ message, id: Date.now() });
  }, []);

  const setMetadata = useCallback(
    (nextMetadata: DocumentMetadata) => {
      setMetadataState(nextMetadata);
      setDocuments((current) =>
        current.map((document) =>
          document.id === activeDocumentId
            ? {
                ...document,
                title: nextMetadata.title.trim() || document.title,
                publisher: nextMetadata.publisher.trim() || document.publisher,
              }
            : document,
        ),
      );
    },
    [activeDocumentId],
  );

  const setMetadataResolved = useCallback(
    (value: boolean) => {
      patchWorkflow(activeDocumentId, { metadataResolved: value });
    },
    [activeDocumentId, patchWorkflow],
  );

  const setApprovedAt = useCallback(
    (value: string | null) => {
      patchWorkflow(activeDocumentId, { approvedAt: value });
      if (activeDocumentId) {
        setDocuments((current) => current.map((document) => (
          document.id === activeDocumentId ? { ...document, approvedAt: value } : document
        )));
      }
    },
    [activeDocumentId, patchWorkflow],
  );

  const addDocuments = useCallback((incoming: DocumentSummary[]) => {
    if (!incoming.length) return;
    setDocuments((current) => {
      const existingIds = new Set(current.map((document) => document.id));
      return [
        ...current,
        ...incoming.filter((document) => !existingIds.has(document.id)),
      ];
    });
    setActiveDocumentId((current) => current ?? incoming[0].id);
    setUploaded(true);
    // Seed each document's own sign-off state from the backend record so an
    // approval on one document is never shown against another.
    setWorkflowByDocument((current) => {
      const next = { ...current };
      incoming.forEach((document) => {
        if (!next[document.id]) {
          next[document.id] = {
            ...emptyWorkflow(),
            approvedAt: document.approvedAt ?? null,
            metadataResolved: Boolean(document.metadataConfirmed),
          };
        }
      });
      return next;
    });
    setDocumentProcessing((current) => {
      const next = { ...current };
      incoming.forEach((document) => {
        if (!next[document.id]) {
          const state = document.processingState ?? "idle";
          next[document.id] = {
            state,
            startedAt: null,
            durationMs: state === "complete" ? 1 : 6000,
            currentStep: state === "complete" ? processingSteps.length - 1 : 0,
            progress: state === "complete" ? 100 : 0,
            remainingSeconds: 0,
            message: state === "complete" ? "Ready for review" : undefined,
          };
        }
      });
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    documentService
      .listDocuments()
      .then((existing) => {
        if (!cancelled && existing.length) addDocuments(existing);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [addDocuments]);

  const removeDocument = useCallback(
    (id: string) => {
      setDocuments((current) => {
        const next = current.filter((document) => document.id !== id);
        setActiveDocumentId((activeId) =>
          activeId === id ? (next[0]?.id ?? null) : activeId,
        );
        if (!next.length) setUploaded(false);
        return next;
      });
      setDocumentProcessing((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      setWorkflowByDocument((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      void queryClient.removeQueries({ queryKey: ["review-items", id] });
      void queryClient.removeQueries({ queryKey: ["metadata", id] });
      void queryClient.removeQueries({ queryKey: ["publication", id] });
      void documentService.removeDocument(id).catch(() => undefined);
    },
    [queryClient],
  );

  const selectDocument = useCallback((id: string) => {
    setActiveDocumentId(id);
  }, []);

  const startDocumentProcessing = useCallback(
    (id: string) => {
      const documentIndex = Math.max(
        0,
        documents.findIndex((document) => document.id === id),
      );
      const durationMs = 5200 + (documentIndex % 4) * 1600;
      setDocumentProcessing((current) => ({
        ...current,
        [id]: {
          state: "running",
          startedAt: Date.now(),
          durationMs,
          currentStep: 0,
          progress: 1,
          remainingSeconds: Math.ceil(durationMs / 1000),
        },
      }));

      patchWorkflow(id, emptyWorkflow());
      setUploaded(true);
      void documentService
        .startProcessing(id)
        .then((job) =>
          setDocumentProcessing((current) => ({ ...current, [id]: job })),
        )
        .catch(() =>
          setDocumentProcessing((current) => ({
            ...current,
            [id]: {
              ...(current[id] ?? {
                startedAt: null,
                durationMs: 0,
                currentStep: 0,
                progress: 0,
                remainingSeconds: 0,
              }),
              state: "failed",
            },
          })),
        );
    },
    [documents, patchWorkflow],
  );

  const stopDocumentProcessing = useCallback((id: string) => {
    setDocumentProcessing((current) => ({
      ...current,
      [id]: {
        state: "idle",
        startedAt: null,
        durationMs: current[id]?.durationMs ?? 6000,
        currentStep: 0,
        progress: 0,
        remainingSeconds: 0,
      },
    }));
    void documentService.stopProcessing(id);
  }, []);

  const runningDocumentIds = Object.entries(documentProcessing)
    .filter(([, job]) => job.state === "running")
    .map(([id]) => id)
    .join("|");

  useEffect(() => {
    if (!runningDocumentIds) return;
    let cancelled = false;

    const refreshProcessingJobs = async () => {
      const ids = runningDocumentIds.split("|");
      const results = await Promise.allSettled(
        ids.map(async (id) => {
          const job = await documentService.getProcessingStatus(id);
          const document =
            job.state === "complete"
              ? await documentService.getDocument(id)
              : null;
          return { id, job, document };
        }),
      );
      if (cancelled) return;
      setDocumentProcessing((current) => {
        const next = { ...current };
        results.forEach((result) => {
          if (result.status === "fulfilled")
            next[result.value.id] = result.value.job;
        });
        return next;
      });
      const completedSummaries = results.flatMap((result) =>
        result.status === "fulfilled" && result.value.document
          ? [result.value.document]
          : [],
      );
      if (completedSummaries.length) {
        const summariesById = new Map(
          completedSummaries.map((document) => [document.id, document]),
        );
        setDocuments((current) =>
          current.map((document) => summariesById.get(document.id) ?? document),
        );
      }
    };

    void refreshProcessingJobs();
    const timer = window.setInterval(() => void refreshProcessingJobs(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runningDocumentIds]);

  const cacheReviewItem = useCallback(
    (updated: ReviewItem) => {
      queryClient.setQueryData<ReviewItem[]>(reviewQueryKey, (current = []) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    },
    [queryClient, reviewQueryKey],
  );

  const setReviewStatus = useCallback(
    async (id: string, status: ReviewStatus) => {
      const updated = await reviewService.setStatus(
        id,
        status,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      cacheReviewItem(updated);
      return updated;
    },
    [activeDocumentId, cacheReviewItem, setApprovedAt],
  );

  const updateReviewText = useCallback(
    async (id: string, text: string) => {
      const updated = await reviewService.updateText(
        id,
        text,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      cacheReviewItem(updated);
    },
    [activeDocumentId, cacheReviewItem, setApprovedAt],
  );

  const updateReviewTable = useCallback(
    async (id: string, table: ReviewTableData) => {
      const updated = await reviewService.updateTable(
        id,
        table,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      cacheReviewItem(updated);
    },
    [activeDocumentId, cacheReviewItem, setApprovedAt],
  );

  const updateReviewLabel = useCallback(
    async (id: string, type: ReviewType, label: string) => {
      const updated = await reviewService.updateLabel(
        id,
        type,
        label,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      cacheReviewItem(updated);
    },
    [activeDocumentId, cacheReviewItem, setApprovedAt],
  );

  const saveReviewItem = useCallback(
    async (id: string, changes: ReviewUpdate) => {
      const updated = await reviewService.saveItem(
        id,
        changes,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      cacheReviewItem(updated);
      return updated;
    },
    [activeDocumentId, cacheReviewItem, setApprovedAt],
  );

  const bulkUpdateReviewItems = useCallback(
    async (ids: string[], changes: ReviewUpdate) => {
      const updated = await reviewService.bulkUpdate(
        ids,
        changes,
        activeDocumentId ?? undefined,
      );
      setApprovedAt(null);
      queryClient.setQueryData<ReviewItem[]>(reviewQueryKey, (current = []) => {
        const replacements = new Map(updated.map((item) => [item.id, item]));
        return current.map((item) => replacements.get(item.id) ?? item);
      });
      return updated;
    },
    [activeDocumentId, queryClient, reviewQueryKey, setApprovedAt],
  );

  const resolveAllReviews = useCallback(async () => {
    const updated = await reviewService.resolveAll(
      activeDocumentId ?? undefined,
    );
    setApprovedAt(null);
    queryClient.setQueryData(reviewQueryKey, updated);
  }, [activeDocumentId, queryClient, reviewQueryKey, setApprovedAt]);

  const pendingCount = useMemo(
    () =>
      reviewItems.filter(
        (item) =>
          item.status === "pending" || item.status === "needs_attention",
      ).length,
    [reviewItems],
  );
  const resolvedCount = reviewItems.length - pendingCount;

  const requiredManualChecks = useMemo<ManualCheckKey[]>(() => {
    const keys: ManualCheckKey[] = ["content"];
    const hasVisualFlags = reviewItems.some(
      (item) =>
        item.type === "table" ||
        item.type === "document_index" ||
        item.type === "box_section" ||
        item.type === "picture",
    );
    if (hasVisualFlags) keys.push("tables");
    if (metadata.citations.trim()) keys.push("citations");
    return keys;
  }, [metadata.citations, reviewItems]);

  const toggleManualCheck = useCallback(
    (key: ManualCheckKey) => {
      if (!activeDocumentId) return;
      setWorkflowByDocument((current) => {
        const workflow = current[activeDocumentId] ?? emptyWorkflow();
        return {
          ...current,
          [activeDocumentId]: {
            ...workflow,
            manualChecks: {
              ...workflow.manualChecks,
              [key]: !workflow.manualChecks[key],
            },
          },
        };
      });
    },
    [activeDocumentId],
  );

  const setAllManualChecks = useCallback(
    (value: boolean) => {
      patchWorkflow(activeDocumentId, {
        manualChecks: { content: value, tables: value, citations: value },
      });
    },
    [activeDocumentId, patchWorkflow],
  );

  // Final approval is based only on automated workflow state. Reviewer
  // checkboxes were removed from the approval gate; their work is already
  // represented by resolved flags and confirmed metadata.
  const approvalReady = pendingCount === 0 && metadataResolved;

  const activeDocument = useMemo(
    () =>
      documents.find((document) => document.id === activeDocumentId) ?? null,
    [activeDocumentId, documents],
  );
  const completedDocuments = useMemo(
    () =>
      documents.filter(
        (document) => documentProcessing[document.id]?.state === "complete",
      ),
    [documentProcessing, documents],
  );
  const runningDocuments = useMemo(
    () =>
      documents.filter(
        (document) => documentProcessing[document.id]?.state === "running",
      ),
    [documentProcessing, documents],
  );

  useEffect(() => {
    if (completedDocuments.length > 0) {
      unlock("review");
      markDone("upload");
    }
  }, [completedDocuments.length, markDone, unlock]);

  useEffect(() => {
    if (approvedAt) {
      unlock("metadata");
      unlock("approval");
      unlock("preview");
    } else if (metadataResolved) {
      unlock("metadata");
      unlock("approval");
    }
  }, [approvedAt, metadataResolved, unlock]);

  const resetWorkflow = useCallback(() => {
    documents.forEach(
      (document) =>
        void documentService.removeDocument(document.id).catch(() => undefined),
    );
    void queryClient.invalidateQueries({ queryKey: ["review-items"] });
    setDocuments([]);
    setActiveDocumentId(null);
    setDocumentProcessing({});
    setWorkflowByDocument({});
    setUploaded(false);
    setMetadataState(emptyMetadata);
    setUnlocked(initialUnlocked);
    setDoneStages(new Set());
  }, [documents, queryClient]);

  const value = useMemo<KonverterContextValue>(
    () => ({
      documents,
      activeDocument,
      activeDocumentId,
      addDocuments,
      removeDocument,
      selectDocument,
      documentProcessing,
      completedDocuments,
      runningDocuments,
      startDocumentProcessing,
      stopDocumentProcessing,
      uploaded,
      setUploaded,
      metadata,
      setMetadata,
      metadataResolved,
      setMetadataResolved,
      approvedAt,
      setApprovedAt,
      unlocked,
      unlock,
      doneStages,
      markDone,
      reviewItems,
      reviewLoading,
      setReviewStatus,
      updateReviewText,
      updateReviewTable,
      updateReviewLabel,
      saveReviewItem,
      bulkUpdateReviewItems,
      resolveAllReviews,
      pendingCount,
      resolvedCount,
      manualChecks,
      requiredManualChecks,
      toggleManualCheck,
      setAllManualChecks,
      approvalReady,
      toastState,
      showToast,
      resetWorkflow,
    }),
    [
      documents,
      activeDocument,
      activeDocumentId,
      addDocuments,
      removeDocument,
      selectDocument,
      documentProcessing,
      completedDocuments,
      runningDocuments,
      startDocumentProcessing,
      stopDocumentProcessing,
      uploaded,
      metadata,
      setMetadata,
      metadataResolved,
      setMetadataResolved,
      approvedAt,
      setApprovedAt,
      unlocked,
      unlock,
      doneStages,
      markDone,
      reviewItems,
      reviewLoading,
      setReviewStatus,
      updateReviewText,
      updateReviewTable,
      updateReviewLabel,
      saveReviewItem,
      bulkUpdateReviewItems,
      resolveAllReviews,
      pendingCount,
      resolvedCount,
      manualChecks,
      requiredManualChecks,
      toggleManualCheck,
      setAllManualChecks,
      approvalReady,
      toastState,
      showToast,
      resetWorkflow,
    ],
  );

  return (
    <KonverterContext.Provider value={value}>
      {children}
    </KonverterContext.Provider>
  );
}

export function useKonverter(): KonverterContextValue {
  const value = useContext(KonverterContext);
  if (!value)
    throw new Error("useKonverter must be used inside KonverterProvider");
  return value;
}
