import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KonverterProvider, useKonverter } from "../state/KonverterContext";
import { testDocument, testMetadata } from "../test/fixtures";
import { resetTestServices } from "../test/serviceMocks";
import { ApprovalPage } from "./ApprovalPage";

function SeedTwoDocuments() {
  const {
    addDocuments,
    setMetadata,
    setApprovedAt,
    selectDocument,
    activeDocumentId,
  } = useKonverter();
  const stage = useRef(0);
  useEffect(() => {
    if (stage.current === 0) {
      const second = {
        ...testDocument,
        id: "second-document",
        fileName: "second.pdf",
        title: "Second Report",
      };
      addDocuments([testDocument, second]);
      setMetadata(testMetadata);
      stage.current = 1;
    } else if (stage.current === 1 && activeDocumentId === testDocument.id) {
      setApprovedAt("2026-08-01T10:00:00Z");
      stage.current = 2;
    } else if (stage.current === 2) {
      selectDocument("second-document");
      stage.current = 3;
    }
  });
  return null;
}

vi.mock("../services", () => import("../test/serviceMocks"));

function SeedApprovalDocument() {
  const { addDocuments, setMetadata } = useKonverter();
  useEffect(() => {
    addDocuments([testDocument]);
    setMetadata(testMetadata);
  }, [addDocuments, setMetadata]);
  return null;
}

function renderApproval() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <KonverterProvider>
          <SeedApprovalDocument />
          <ApprovalPage />
        </KonverterProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(resetTestServices);
afterEach(cleanup);

describe("ApprovalPage", () => {
  it("never shows one document\u2019s approval against another document", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <KonverterProvider>
            <SeedTwoDocuments />
            <ApprovalPage />
          </KonverterProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "Approve document" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Document approved")).not.toBeInTheDocument();
  });

  it("keeps the final Resolve all control without demo behavior", async () => {
    renderApproval();
    await screen.findByText(/flagged items reviewed/i);

    const resolveAll = screen.getByRole("button", { name: "Resolve all" });
    expect(
      screen.queryByText(/demo|sample|prototype/i),
    ).not.toBeInTheDocument();
    fireEvent.click(resolveAll);

    expect(await screen.findByText("All 3 items reviewed")).toBeInTheDocument();
  });
});
