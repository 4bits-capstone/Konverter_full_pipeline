import {
  ArrowLeft,
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Code2,
  Download,
  FileJson2,
  Info,
  ListTree,
  Network,
  Quote,
  RotateCcw,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ConfidenceBadge } from "../components/ConfidenceBadge";
import { DoclingContent } from "../components/DoclingContent";
import { ReportSummaryCard, type ReportSummaryRecord } from "../components/ReportSummaryCard";
import { emptyMetadata } from "../config/workflow";
import { converterStagePath } from "../lib/converterRoutes";
import type { DoclingSection } from "../lib/docling";
import {
  formatPublicationDate,
} from "../lib/publicationFormatting";
import { publicationService } from "../services";
import { useKonverter } from "../state/KonverterContext";

const JSON_LD_SCRIPT_ID = "konverter-publication-json-ld";

interface ValidationCheck {
  label: string;
  ok: boolean;
  detail: string;
}

function buildValidationChecks(
  publication: import("../lib/docling").DoclingPublication | undefined,
  metadata: { title: string; publisher: string; publishedDate: string },
  jsonLd: Record<string, unknown>,
): ValidationCheck[] {
  const sections = publication?.sections ?? [];
  const allBlocks = sections.flatMap((section) => section.blocks);

  let headingIssues = 0;
  sections.forEach((section) => {
    let previousLevel = 1; // The section title renders as the H1.
    section.blocks.forEach((block) => {
      if (block.type !== "heading") return;
      if (block.level > previousLevel + 1) headingIssues += 1;
      previousLevel = block.level;
    });
  });

  const tables = allBlocks.filter((block) => block.type === "table");
  const tablesWithoutHeaders = tables.filter(
    (table) =>
      !table.rows.some((row) =>
        row.some((cell) => cell.columnHeader || cell.rowHeader),
      ),
  ).length;

  const figures = allBlocks.filter((block) => block.type === "figure");
  const figuresWithoutCaptions = figures.filter(
    (figure) => !figure.caption.trim(),
  ).length;

  const graph = Array.isArray(jsonLd["@graph"])
    ? (jsonLd["@graph"] as Array<Record<string, unknown>>)
    : null;

  const reportNode =
    graph?.find((node) => node["@type"] === "Report") ??
    (graph ? undefined : jsonLd);
  const jsonLdOk =
    jsonLd["@context"] === "https://schema.org" &&
    Boolean(reportNode?.["@type"]) &&
    Boolean(reportNode?.["name"]);
  const metadataOk = Boolean(
    metadata.title.trim() &&
    metadata.publisher.trim() &&
    metadata.publishedDate.trim(),
  );

  return [
    {
      label: "Semantic content structure",
      ok: sections.length > 0 && allBlocks.length > 0,
      detail: sections.length
        ? `${sections.length} section${sections.length === 1 ? "" : "s"}, ${allBlocks.length} semantic blocks`
        : "No sections were generated",
    },
    {
      label: "Heading hierarchy (no skipped levels)",
      ok: headingIssues === 0,
      detail: headingIssues
        ? `${headingIssues} heading${headingIssues === 1 ? "" : "s"} skip a level`
        : "Every heading nests one level at a time",
    },
    {
      label: "Tables include header cells",
      ok: tablesWithoutHeaders === 0,
      detail: tables.length
        ? tablesWithoutHeaders
          ? `${tablesWithoutHeaders} of ${tables.length} tables have no header cells`
          : `All ${tables.length} table${tables.length === 1 ? "" : "s"} carry header semantics`
        : "No tables in this document",
    },
    {
      label: "Figures carry alternative text",
      ok: figuresWithoutCaptions === 0,
      detail: figures.length
        ? figuresWithoutCaptions
          ? `${figuresWithoutCaptions} of ${figures.length} figures have an empty caption`
          : `All ${figures.length} figure${figures.length === 1 ? "" : "s"} have captions used as alt text`
        : "No figures in this document",
    },
    {
      label: "JSON-LD metadata valid",
      ok: jsonLdOk,
      detail: jsonLdOk
        ? `schema.org ${String(reportNode?.["@type"])} graph with ${graph ? graph.length : 1} linked node${graph && graph.length !== 1 ? "s" : ""}`
        : "The embedded JSON-LD is missing its Report node, name or context",
    },
    {
      label: "Required metadata complete",
      ok: metadataOk,
      detail: metadataOk
        ? "Title, publisher and published date confirmed"
        : "Title, publisher or published date is missing",
    },
  ];
}

function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const container = document.getElementById("main-content");
    if (!container) return;
    const onScroll = () => setVisible(container.scrollTop > 480);
    onScroll();
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  const scrollToTop = () => {
    const container = document.getElementById("main-content");
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    container?.scrollTo({
      top: 0,
      behavior: reducedMotion ? "auto" : "smooth",
    });
  };

  return (
    <button
      type="button"
      className={`back-to-top ${visible ? "is-visible" : ""}`}
      aria-label="Back to top of page"
      onClick={scrollToTop}
    >
      <ArrowUp aria-hidden="true" />
      Back to top
    </button>
  );
}

function sectionUrl(documentId: string, section?: DoclingSection): string {
  if (!section) return `review-preview.local/documents/${documentId}`;
  return `review-preview.local/documents/${documentId}/${section.id}`;
}

function isChapterSection(section: DoclingSection): boolean {
  if (typeof section.isChapter === "boolean") return section.isChapter;
  return /^\s*(?:(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b|\d+[.)]\s+)/i.test(
    section.displayTitle,
  );
}

function recommendationSnippets(sections: DoclingSection[]): string[] {
  const recommendationSections = sections.filter((section) => /recommend/i.test(section.displayTitle))
  const candidates = recommendationSections.flatMap((section) => section.blocks.flatMap((block) => {
    if (block.type === 'paragraph') return [block.text]
    if (block.type === 'list') return block.items.map((item) => item.text)
    if (block.type === 'box_section' && /recommend/i.test(`${block.title} ${block.variant}`)) {
      return block.blocks.flatMap((child) => child.type === 'paragraph' ? [child.text] : child.type === 'list' ? child.items.map((item) => item.text) : [])
    }
    return []
  }))
  return candidates.map((value) => value.replace(/\s+/g, ' ').trim()).filter((value) => value.length >= 24).slice(0, 3)
}

function projectSlug(title: string): string {
  const projectTitle = title
    .trim()
    .split(/\s*:\s*/, 1)[0]
    .replace(
      /\s+[-\u2013\u2014]\s+(?:consultation paper|issues paper|final report|report)$/i,
      '',
    )
  return projectTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'publication'
}

function scrollToReaderHeading(headingId: string): void {
  const target = document.getElementById(headingId);
  if (!target) return;

  const scrollContainer = target.closest<HTMLElement>("#main-content");
  if (scrollContainer?.scrollTo) {
    const targetTop =
      target.getBoundingClientRect().top -
      scrollContainer.getBoundingClientRect().top +
      scrollContainer.scrollTop -
      18;
    scrollContainer.scrollTo({
      top: Math.max(0, targetTop),
      behavior: "smooth",
    });
    return;
  }

  target.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

export function PreviewPage() {
  const navigate = useNavigate();
  const { activeDocument, activeDocumentId, resetWorkflow } = useKonverter();
  const publicationQuery = useQuery({
    queryKey: ["publication", activeDocumentId ?? "none"],
    queryFn: () => publicationService.get(activeDocumentId!),
    enabled: Boolean(activeDocumentId),
  });
  const publication = publicationQuery.data?.publication;
  const pageMetadata = publicationQuery.data?.metadata ?? emptyMetadata;
  const jsonLd = publicationQuery.data?.jsonLd ?? {};
  const documentConfidence = publicationQuery.data?.confidence ?? null;
  const publicationSections = publication?.sections ?? [];
  const firstPublicationSection = publicationSections[0];
  const firstChapterSection = publicationSections.find(isChapterSection);
  const publicationSummary =
    publication?.summary?.find((summary) => summary.trim()) ??
    `This publication presents the reviewed content of ${pageMetadata.title}.`;
  const [readerOpen, setReaderOpen] = useState(false);
  const [selectedSectionId, setSelectedSectionId] = useState(
    firstPublicationSection?.id ?? "",
  );
  const [readerTarget, setReaderTarget] = useState(
    firstPublicationSection?.headings[0]?.id ?? "",
  );
  const publicationTitleRef = useRef<HTMLHeadingElement>(null);
  const chapterTitleRef = useRef<HTMLHeadingElement>(null);
  const readerWasOpened = useRef(false);

  const selectedSection =
    publicationSections.find((section) => section.id === selectedSectionId) ??
    firstPublicationSection;
  const validationChecks = useMemo(
    () => buildValidationChecks(publication, pageMetadata, jsonLd),
    [jsonLd, pageMetadata, publication],
  );
  const recommendations = useMemo(() => recommendationSnippets(publicationSections), [publicationSections]);
  const citation = pageMetadata.citations.split(';').map((value) => value.trim()).find(Boolean)
    ?? `${pageMetadata.publisher}, ${pageMetadata.title}`;
  const reportNumber = citation.match(/(?:Report(?:\s+No)?\.?\s*)(\d+)/i)?.[1] ?? '—';
  const previewReport: ReportSummaryRecord = {
    title: pageMetadata.title,
    reportNumber,
    pageCount: activeDocument?.pages || publication?.stats.pages || 0,
    publisher: pageMetadata.publisher,
    publishedDate: formatPublicationDate(pageMetadata.publishedDate),
    currentAsOf: formatPublicationDate(pageMetadata.publishedDate),
    jurisdiction: pageMetadata.jurisdiction,
    status: 'Reviewed publication',
    summary: publicationSummary,
    citation,
    topics: Array.from(new Set([pageMetadata.jurisdiction, 'Law reform'].filter(Boolean))),
    coverUrl: activeDocumentId ? publicationService.coverUrl(activeDocumentId) : '',
    localPdfUrl: activeDocumentId ? publicationService.sourceUrl(activeDocumentId) : '#',
  };
  const projectUrl = `/project/${projectSlug(pageMetadata.title)}/`;
  const selectedSectionIndex = selectedSection
    ? publicationSections.findIndex(
        (section) => section.id === selectedSection.id,
      )
    : -1;
  const previousSection =
    selectedSectionIndex > 0
      ? publicationSections[selectedSectionIndex - 1]
      : undefined;
  const nextSection =
    selectedSectionIndex >= 0 &&
    selectedSectionIndex < publicationSections.length - 1
      ? publicationSections[selectedSectionIndex + 1]
      : undefined;

  useEffect(() => {
    if (!firstPublicationSection) return;
    setSelectedSectionId((current) =>
      publicationSections.some((section) => section.id === current)
        ? current
        : firstPublicationSection.id,
    );
    setReaderTarget(
      (current) => current || firstPublicationSection.headings[0]?.id || "",
    );
  }, [firstPublicationSection, publicationSections]);

  useEffect(() => {
    if (readerOpen) {
      readerWasOpened.current = true;
      chapterTitleRef.current?.focus({ preventScroll: true });
    } else if (readerWasOpened.current) {
      publicationTitleRef.current?.focus({ preventScroll: true });
    }
  }, [readerOpen, selectedSectionId]);

  useEffect(() => {
    if (readerOpen && readerTarget) scrollToReaderHeading(readerTarget);
  }, [readerOpen, readerTarget, selectedSectionId]);

  useEffect(() => {
    if (!Object.keys(jsonLd).length) return;

    document.getElementById(JSON_LD_SCRIPT_ID)?.remove();
    const script = document.createElement("script");
    script.id = JSON_LD_SCRIPT_ID;
    script.type = "application/ld+json";
    script.text = JSON.stringify(jsonLd, null, 2).replaceAll("<", "\\u003c");
    document.head.appendChild(script);

    return () => script.remove();
  }, [jsonLd]);

  const downloadHtml = () => {
    if (activeDocumentId)
      window.location.assign(
        publicationService.exportUrl(activeDocumentId, "html"),
      );
  };

  const downloadJson = () => {
    if (activeDocumentId)
      window.location.assign(
        publicationService.exportUrl(activeDocumentId, "jsonld"),
      );
  };

  const downloadStructured = () => {
    if (activeDocumentId)
      window.location.assign(
        publicationService.exportUrl(activeDocumentId, "structured"),
      );
  };

  const startNewUpload = () => {
    resetWorkflow();
    navigate(converterStagePath("upload"));
  };

  const openReader = (
    event: MouseEvent<HTMLElement>,
    section: DoclingSection,
    headingId?: string,
  ) => {
    event.preventDefault();
    setSelectedSectionId(section.id);
    setReaderTarget(headingId ?? section.headings[0]?.id ?? "");
    setReaderOpen(true);
  };

  const navigateWithinReader = (
    event: MouseEvent<HTMLAnchorElement>,
    headingId: string,
  ) => {
    event.preventDefault();
    if (readerTarget === headingId) scrollToReaderHeading(headingId);
    else setReaderTarget(headingId);
  };

  const changeReaderSection = (section: DoclingSection) => {
    setSelectedSectionId(section.id);
    setReaderTarget(section.headings[0]?.id ?? "");
  };

  if (!activeDocumentId) {
    return (
      <section className="screen active" aria-labelledby="preview-heading">
        <div className="section-title preview-titlebar">
          <div>
            <span className="eyebrow">Stage 4 of 4</span>
            <h2 id="preview-heading">Publication preview</h2>
          </div>
        </div>
        <div className="banner banner-warn">
          <Info />
          <div>Select and approve a document before opening its preview.</div>
        </div>
      </section>
    );
  }

  if (publicationQuery.isLoading) {
    return (
      <section className="screen active" aria-labelledby="preview-heading">
        <div className="section-title preview-titlebar">
          <div>
            <span className="eyebrow">Stage 4 of 4</span>
            <h2 id="preview-heading">Publication preview</h2>
          </div>
        </div>
        <div className="panel panel-pad workflow-loading" role="status">
          <span className="spinner" />
          Generating the reviewed landing page, accessible HTML and JSON-LD…
        </div>
      </section>
    );
  }

  if (publicationQuery.isError || !publication) {
    return (
      <section className="screen active" aria-labelledby="preview-heading">
        <div className="section-title preview-titlebar">
          <div>
            <span className="eyebrow">Stage 4 of 4</span>
            <h2 id="preview-heading">Publication preview</h2>
          </div>
        </div>
        <div className="banner banner-warn">
          <Info />
          <div>
            The generated publication could not be loaded. Return to Review,
            confirm the document changes, then run the final system checks again.
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="screen active" aria-labelledby="preview-heading">
      <div className="section-title preview-titlebar">
        <div>
          <span className="eyebrow">Stage 4 of 4</span>
          <h2 id="preview-heading">Publication preview</h2>
          <p className="lead">Check the reviewed reading experience and export the accessible version when it is ready.</p>
        </div>
        <div className="preview-title-actions">
          {documentConfidence?.band && documentConfidence.score != null && (
            <span title={documentConfidence.source}>
              <ConfidenceBadge
                band={documentConfidence.band}
                score={documentConfidence.score}
                compact
              />
            </span>
          )}
          <span className="sr-only">Approved preview</span>
          <details className="export-menu">
            <summary className="btn btn-primary btn-sm">
              <Download />
              Export
              <ChevronDown aria-hidden="true" />
            </summary>
            <div
              className="export-popover"
              role="menu"
              aria-label="Export formats"
            >
              <button type="button" role="menuitem" onClick={downloadHtml}>
                <Code2 />
                <span>
                  <strong>Accessible HTML</strong>
                  <small>Collapsible full report</small>
                </span>
              </button>
              <button type="button" role="menuitem" onClick={downloadJson}>
                <FileJson2 />
                <span>
                  <strong>JSON-LD</strong>
                  <small>Structured metadata</small>
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={downloadStructured}
              >
                <Network />
                <span>
                  <strong>Structured JSON</strong>
                  <small>Reviewed document blocks</small>
                </span>
              </button>
            </div>
          </details>
        </div>
      </div>

      <nav className="preview-navigation" aria-label="Preview navigation">
        <div>
          <strong>Preview safely</strong>
          <span>The original PDF is unchanged. Return to Review to adjust the converted document.</span>
        </div>
        <div className="preview-navigation-actions">
          <button
            className="btn btn-primary btn-sm"
            onClick={() => navigate(converterStagePath("review"))}
          >
            <ArrowLeft />
            Return to review
          </button>
          <button
            className="btn btn-outline btn-sm"
            type="button"
            onClick={startNewUpload}
          >
            <RotateCcw aria-hidden="true" />
            Start new upload
          </button>
        </div>
      </nav>

      <div className="banner banner-info preview-banner">
        <Info />
        <div>
          Reviewed Docling data is loaded: {publication.stats.pages} pages,{" "}
          {publication.stats.textItems.toLocaleString()} text items,{" "}
          {publication.stats.tables} tables, {publication.stats.pictures}{" "}
          picture records and {publication.stats.footnotes} footnotes. Select
          any section to read its extracted content.
        </div>
      </div>

      <div className="preview-grid">
        <div className="published">
          <div className="pub-browser" aria-hidden="true">
            <span className="pub-dot" />
            <span className="pub-dot" />
            <span className="pub-dot" />
            <span className="pub-url">
              {readerOpen
                ? sectionUrl(activeDocumentId, selectedSection)
                : sectionUrl(activeDocumentId)}
            </span>
          </div>

          <article
            className="vlrc-preview"
            aria-labelledby={readerOpen ? "chapter-title" : "publication-title"}
          >
            <header className="vlrc-masthead">
              <div
                className="vlrc-wordmark"
                aria-label="Victorian Law Reform Commission"
              >
                <img
                  src="/vlrc_logo.png"
                  alt="Victorian Law Reform Commission logo"
                  style={{ width: "150px", height: "auto" }}
                />
              </div>
              <span className="vlrc-masthead-label">Publication</span>
            </header>

            {!readerOpen ? (
              <div className="vlrc-preview-body">
                <div className="preview-report-card-shell">
                  <ReportSummaryCard
                    report={previewReport}
                    root="header"
                    headingLevel={1}
                    headingId="publication-title"
                    headingRef={publicationTitleRef}
                    headingTabIndex={-1}
                    className="preview-report-card"
                    actions={(
                      <>
                        <button className="button button-primary" type="button" onClick={(event) => firstPublicationSection && openReader(event, firstPublicationSection)}>
                          <BookOpen aria-hidden="true" /> Read online
                        </button>
                        <a className="button button-secondary" href={previewReport.localPdfUrl} target="_blank" rel="noreferrer">
                          <Download aria-hidden="true" /> Download PDF
                        </a>
                        <a className="button button-secondary" href={projectUrl}>
                          <ChevronRight aria-hidden="true" /> Go to Project
                        </a>
                        <a className="text-action" href="#report-contents"><ListTree aria-hidden="true" /> View report sections</a>
                        <a className="text-action" href="#preview-citation"><Quote aria-hidden="true" /> View citation</a>
                      </>
                    )}
                  />
                </div>

                <div className="preview-publication-main">
                  {recommendations.length > 0 && (
                    <section className="key-recommendations" aria-labelledby="recommendations-heading">
                      <span className="eyebrow">At a glance</span><h2 id="recommendations-heading">Key recommendations</h2>
                      <div>{recommendations.map((recommendation, index) => <article key={`${recommendation}-${index}`}><strong>{String(index + 1).padStart(2, '0')}</strong><p>{recommendation}</p></article>)}</div>
                    </section>
                  )}

                  <section className="vlrc-contents" id="report-contents" aria-labelledby="contents-heading">
                    <div className="contents-heading-row">
                      <div><span className="eyebrow">Full report</span><h2 id="contents-heading">Table of contents</h2></div>
                    </div>

                    <div className="vlrc-accordion" aria-label="Complete report chapters">
                      {publicationSections.map((section) => {
                        if (!isChapterSection(section)) {
                          return (
                            <div className="vlrc-direct-item" key={section.id}>
                              <a
                                href={`#${section.id}`}
                                onClick={(event) => openReader(event, section)}
                              >
                                <span>{section.displayTitle}</span>
                                <ChevronRight aria-hidden="true" />
                              </a>
                            </div>
                          );
                        }
                        const panelId = `${section.id}-subsections`;
                        const majorHeadings = section.headings.filter((heading) => heading.level === 2).sort((left, right) => (left.tocSequence ?? Number.MAX_SAFE_INTEGER) - (right.tocSequence ?? Number.MAX_SAFE_INTEGER) || (left.page ?? 0) - (right.page ?? 0));
                        return (
                          <details className="vlrc-accordion-item" key={section.id} open={section.id === firstChapterSection?.id}>
                            <summary aria-controls={panelId}><span>{section.displayTitle}</span><ChevronDown className="accordion-chevron" aria-hidden="true" /></summary>
                            <div className="vlrc-accordion-panel" id={panelId}>
                              <ul><li className="vlrc-read-full"><a href={`#${section.id}`} onClick={(event) => openReader(event, section)}>Read full section</a></li>{majorHeadings.map((heading) => <li key={heading.id}><a href={`#${heading.id}`} onClick={(event) => openReader(event, section, heading.id)}>{heading.text}</a></li>)}</ul>
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  </section>

                  <section className="preview-citation-card" id="preview-citation" aria-labelledby="preview-citation-heading">
                    <Quote aria-hidden="true" />
                    <div><span className="eyebrow">Source and citation</span><h2 id="preview-citation-heading">Cite this report</h2><blockquote>{previewReport.citation}</blockquote><p>Published by {previewReport.publisher}.</p></div>
                  </section>
                </div>
              </div>
            ) : selectedSection ? (
              <div className="vlrc-reader">
                <nav className="vlrc-reader-breadcrumb" aria-label="Breadcrumb">
                  <button type="button" onClick={() => setReaderOpen(false)}>
                    <ArrowLeft aria-hidden="true" />
                    {pageMetadata.title}
                  </button>
                  <ChevronRight aria-hidden="true" />
                  <span aria-current="page">
                    {selectedSection.displayTitle}
                  </span>
                </nav>

                <div className="vlrc-reader-layout">
                  <nav
                    className="vlrc-reader-nav"
                    aria-labelledby="chapter-contents-heading"
                  >
                    <h2 id="chapter-contents-heading">In this section</h2>
                    <ul>
                      {selectedSection.headings.map((heading) => (
                        <li
                          className={`heading-level-${heading.level}`}
                          key={heading.id}
                        >
                          <a
                            href={`#${heading.id}`}
                            aria-current={
                              readerTarget === heading.id
                                ? "location"
                                : undefined
                            }
                            onClick={(event) =>
                              navigateWithinReader(event, heading.id)
                            }
                          >
                            {heading.text}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </nav>

                  <div className="vlrc-reader-content">
                    <div className="chapter-label">{pageMetadata.title}</div>
                    <h1 id="chapter-title" ref={chapterTitleRef} tabIndex={-1}>
                      {selectedSection.displayTitle}
                    </h1>

                    <DoclingContent
                      blocks={selectedSection.blocks}
                      footnotes={selectedSection.footnotes}
                      sectionId={selectedSection.id}
                      figureUrl={(imageKey) =>
                        publicationService.figureUrl(activeDocumentId, imageKey)
                      }
                    />

                    <nav
                      className="reader-pagination"
                      aria-label="Document section pagination"
                    >
                      <button
                        type="button"
                        disabled={!previousSection}
                        onClick={() =>
                          previousSection &&
                          changeReaderSection(previousSection)
                        }
                      >
                        <span>Previous</span>
                        {previousSection?.displayTitle ??
                          "Beginning of document"}
                      </button>
                      <button
                        type="button"
                        disabled={!nextSection}
                        onClick={() =>
                          nextSection && changeReaderSection(nextSection)
                        }
                      >
                        <span>Next</span>
                        {nextSection?.displayTitle ?? "End of document"}
                      </button>
                    </nav>
                  </div>
                </div>
              </div>
            ) : null}

            <footer className="vlrc-site-footer">
              <div>
                <strong>Victorian Law Reform Commission</strong>
                <span>Improving and modernising Victoria&apos;s laws</span>
              </div>
              <nav aria-label="VLRC footer links">
                <a href="https://www.lawreform.vic.gov.au/about-us/" target="_blank" rel="noreferrer">About Us</a>
                <a href="https://www.lawreform.vic.gov.au/all-projects/" target="_blank" rel="noreferrer">All Projects</a>
                <a href="https://www.lawreform.vic.gov.au/publications-and-media/publications/" target="_blank" rel="noreferrer">Publications</a>
                <a href="https://www.lawreform.vic.gov.au/contact-us/" target="_blank" rel="noreferrer">Contact</a>
              </nav>
            </footer>
          </article>
        </div>

        <aside className="pub-side" aria-label="Preview controls">
          <div className="valcard">
            <h4>Accessibility &amp; validation</h4>
            {validationChecks.map((check) => (
              <div
                className={`valrow ${check.ok ? "ok" : "warn"}`}
                key={check.label}
                title={check.detail}
              >
                {check.ok ? (
                  <Check aria-hidden="true" />
                ) : (
                  <Circle aria-hidden="true" />
                )}
                <div className="valrow-text">
                  {check.label}
                  <span className="valrow-detail">{check.detail}</span>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>
      <BackToTop />
    </section>
  );
}
