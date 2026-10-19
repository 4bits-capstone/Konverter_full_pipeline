import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { Link } from "react-router-dom";
import "../styles/landing.css";

const DEMO_URL = "https://komosion.com/support-request/";
const LOGIN_PATH = "/login";

const SECTIONS = [
  { id: "product", label: "Product" },
  { id: "transform", label: "How it works" },
  { id: "engage", label: "Working with us" },
  { id: "faq", label: "FAQ" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

const SCREENS = [
  {
    name: "Upload",
    src: "/landing/screen-upload.webp",
    alt: "Upload stage: drop PDFs or use a sample report",
    title: "Upload documents",
    sub: "Drop in PDFs, or start from a sample report.",
  },
  {
    name: "Processing",
    src: "/landing/screen-processing.webp",
    alt: "Processing queue with progress and time remaining",
    title: "Track processing",
    sub: "Each document processes on its own, with time remaining.",
  },
  {
    name: "Review",
    src: "/landing/screen-review.webp",
    alt: "Review stage: flagged exceptions with the reason each was flagged",
    title: "Review flagged items",
    sub: "Only the items that need a human decision.",
  },
  {
    name: "Metadata",
    src: "/landing/screen-metadata.webp",
    alt: "Metadata stage: fields checked against the publication record and cover page",
    title: "Confirm metadata",
    sub: "Every field checked against the source.",
  },
  {
    name: "Workspace activity",
    src: "/landing/screen-activity.webp",
    alt: "Admin workspace activity: a protected record of every change",
    title: "Workspace activity",
    sub: "A protected record of who changed what, and when.",
  },
];

const STATS = [
  { value: "614", label: "pages in the largest report processed", tone: "" },
  { value: "227", of: "/227", label: "decisions reviewed before export", tone: "kl-stat-sky" },
  { value: "3", label: "outputs from one review: HTML, JSON, JSON-LD", tone: "kl-stat-soft" },
  { value: "4", label: "stages: upload, review, metadata, preview", tone: "kl-stat-navy" },
];

const TREE = [
  { tag: "h1", text: "Report title", indent: 0 },
  { tag: "h2", text: "17 sections", indent: 20 },
  { tag: "table", text: "8 with header cells", indent: 40 },
  { tag: "figure", text: "3 with alt text", indent: 40 },
];

const REPORT_LENGTHS = [
  { name: "Assistance Animals", pages: 88, share: 0.143, color: "#2B82BF" },
  { name: "Funeral and Burial Instructions", pages: 164, share: 0.267, color: "#2A6DAC" },
  { name: "Sex Offences response report", pages: 614, share: 1, color: "#292768" },
];

const CONFIDENCE = [
  { field: "Title", pct: 99 },
  { field: "Publisher", pct: 98 },
  { field: "Jurisdiction", pct: 93 },
  { field: "Published", pct: 0 },
];

const STEPS = [
  { title: "Talk to us", body: "We look at your documents, formats and publishing workflow." },
  { title: "Pilot", body: "Konverter runs on a set of your own reports." },
  { title: "Configure", body: "Metadata rules, roles and outputs are set for your team." },
  { title: "Publish", body: "Your reviewers sign in, approve and export." },
];

const FAQ_WELCOME =
  "Hi, I can answer common questions about Konverter. Pick one below or type your own.";
const FAQ_FALLBACK =
  "I don’t have an answer for that yet. Request a demo and the Komosion team will follow up with you directly.";
const FAQ_ITEMS = [
  {
    q: "Is Konverter self-service?",
    k: ["self", "service", "sign up", "signup", "account", "trial", "login", "set up", "setup", "onboard"],
    a: "No. Komosion sets Konverter up for your organisation. Your team then signs in through the client login to review, approve and export.",
  },
  {
    q: "How large can documents be?",
    k: ["large", "size", "pages", "long", "big", "limit", "how many"],
    a: "Reports of 400+ pages are routine. The largest processed so far is 614 pages. Documents process in the background, so reviewing can start on the first one that finishes.",
  },
  {
    q: "Does the AI publish on its own?",
    k: ["publish", "own", "automatic", "human", "reviewer", "accurate", "accuracy", "mistake", "trust"],
    a: "No. Uncertain structure and metadata are flagged for a reviewer, and export stays locked until every decision is reviewed.",
  },
  {
    q: "What do we get at the end?",
    k: ["get", "output", "format", "html", "json", "export", "deliver", "result"],
    a: "Accessible HTML for your website, structured JSON for AI systems, and schema.org JSON-LD for search and AI discovery.",
  },
  {
    q: "Can we see who changed what?",
    k: ["changed", "audit", "log", "history", "who", "track", "record", "activity"],
    a: "Yes. Every upload, edit and approval is written to a protected activity log that admins can search and filter.",
  },
  {
    q: "How much does it cost?",
    k: ["cost", "price", "pricing", "fee", "pay", "licence", "license", "demo"],
    a: "Pricing depends on your documents and how Konverter is set up for your team. Request a demo and we’ll walk you through the options.",
  },
];

/** Keyword match against the FAQ; an exact question match always wins. */
function answerFaq(text: string) {
  const t = text.toLowerCase();
  let best: (typeof FAQ_ITEMS)[number] | null = null;
  let bestScore = 0;
  for (const item of FAQ_ITEMS) {
    if (item.q.toLowerCase() === t.trim()) return item.a;
    const score = item.k.filter((keyword) => t.includes(keyword)).length;
    if (score > bestScore) {
      bestScore = score;
      best = item;
    }
  }
  return best ? best.a : FAQ_FALLBACK;
}

function LockIcon() {
  return (
    <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
    <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

/**
 * Fades elements in as they scroll into view. Anything already on screen at
 * load is shown straight away so the first paint isn't blank.
 */
function useScrollReveal(rootRef: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const els = Array.from(root.querySelectorAll<HTMLElement>(".kl-rv, .kl-fan"));
    const timers: number[] = [];
    const show = (el: HTMLElement) => {
      if (el.classList.contains("kl-fan") && el.classList.contains("kl-pre")) {
        el.classList.add("kl-revealing");
        timers.push(window.setTimeout(() => el.classList.remove("kl-revealing"), 1600));
      }
      el.classList.remove("kl-pre");
      el.classList.add("kl-in");
    };
    if (!("IntersectionObserver" in window)) {
      els.forEach(show);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            show(entry.target as HTMLElement);
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.2 },
    );
    els.forEach((el) => {
      if (el.getBoundingClientRect().top > window.innerHeight * 0.85) el.classList.add("kl-pre");
      else timers.push(window.setTimeout(() => show(el), 60));
      io.observe(el);
    });
    return () => {
      io.disconnect();
      timers.forEach(window.clearTimeout);
    };
  }, [rootRef]);
}

function useActiveSection() {
  const [active, setActive] = useState<SectionId>("product");
  useEffect(() => {
    const onScroll = () => {
      let current: SectionId = "product";
      for (const { id } of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 140) current = id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return active;
}

function Header() {
  const [menuOpen, setMenuOpen] = useState(false);
  const active = useActiveSection();

  return (
    <>
      <div className="kl-topbar" role="banner">
        <div className="kl-wrap kl-topbar-inner">
          <div className="kl-topbar-left">
            <a href="https://www.komosion.com" aria-label="Komosion home">
              <img className="kl-topbar-logo" src="/landing/komosion-wordmark-white.png" alt="Komosion" />
            </a>
            <span aria-hidden="true" className="kl-topbar-divider kl-hide-md" />
            <span className="kl-tagline kl-hide-md">
              Helping businesses use AI
              <br />
              to be more efficient and effective.
            </span>
          </div>
          <div className="kl-topbar-right">
            <a href="#top" className="kl-brandlock">
              <span className="kl-brandlock-name">
                Konverter
                <span aria-hidden="true" className="kl-square" />
                AI
              </span>
              <span className="kl-brandlock-sub kl-hide-sm">Convert, review and export</span>
            </a>
            <button
              type="button"
              className="kl-menubtn"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="kl-mnav"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
                <path d={menuOpen ? "M6 6l12 12M18 6 6 18" : "M4 7h16M4 12h16M4 17h16"} />
              </svg>
            </button>
          </div>
        </div>
        <nav id="kl-mnav" hidden={!menuOpen} aria-label="Page sections" className="kl-mnav">
          <div className="kl-wrap">
            {SECTIONS.map(({ id, label }) => (
              <a
                key={id}
                href={`#${id}`}
                aria-current={active === id ? "true" : undefined}
                onClick={() => setMenuOpen(false)}
              >
                {label}
                <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </a>
            ))}
          </div>
        </nav>
      </div>

      <nav className="kl-subnav" aria-label="Page sections">
        <div className="kl-wrap kl-subnav-inner">
          <div className="kl-subnav-links">
            {SECTIONS.map(({ id, label }) => (
              <a key={id} href={`#${id}`} aria-current={active === id ? "true" : "false"}>
                {label}
              </a>
            ))}
          </div>
          <div className="kl-subnav-actions">
            <Link to={LOGIN_PATH} className="kl-navlink kl-subnav-login">
              <LockIcon />
              Client login
            </Link>
            <a href={DEMO_URL} className="kl-btn kl-btn-navy kl-btn-pill-sm">
              Request a demo <span aria-hidden="true">→</span>
            </a>
          </div>
        </div>
      </nav>
    </>
  );
}

function Hero() {
  return (
    <div className="kl-wrap kl-hero-inner">
      <p className="kl-hero-kicker">
        <span aria-hidden="true" className="kl-square" />
        AI document conversion for legal &amp; policy publishers
      </p>
      <h1 id="hero-title" className="kl-hero-title">
        <span className="kl-hero-light">Complex PDFs,</span>
        <span className="kl-hero-strong">
          <span className="kl-gradient-text">made</span>
          <span aria-hidden="true" className="kl-hero-badge">
            <svg
              viewBox="0 0 48 48"
              fill="none"
              stroke="#292768"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M28 5H13a4 4 0 0 0-4 4v30a4 4 0 0 0 4 4h22a4 4 0 0 0 4-4V16z" />
              <path d="M28 5v11h11" />
              <path d="M24 36V23M18.5 28.5 24 23l5.5 5.5" />
            </svg>
            <span className="kl-pdfbadge" />
          </span>
          <span className="kl-gradient-text" style={{ paddingRight: ".08em" }}>
            clear.
          </span>
        </span>
      </h1>
      <p className="kl-hero-quote">
        <span aria-hidden="true" className="kl-quote-mark">
          “
        </span>
        <span>
          Konverter converts long legal and policy PDFs into accessible HTML, structured JSON and
          schema.org JSON-LD. AI does the heavy lifting; your reviewers approve every uncertain
          decision.
        </span>
        <span aria-hidden="true" className="kl-quote-mark">
          ”
        </span>
      </p>
      <div className="kl-hero-ctas">
        <a href={DEMO_URL} className="kl-btn kl-btn-navy kl-btn-hero">
          Request a demo
          <span aria-hidden="true" className="kl-btn-hero-plus">
            <svg className="kl-ico" viewBox="0 0 24 24">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </span>
        </a>
        <Link to={LOGIN_PATH} className="kl-navlink kl-hero-login">
          Client login
        </Link>
      </div>
    </div>
  );
}

function ScreenCarousel() {
  const [index, setIndex] = useState(1);
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const startX = useRef(0);
  const moved = useRef(false);
  const last = SCREENS.length - 1;

  const go = useCallback(
    (n: number) => {
      setIndex(Math.max(0, Math.min(last, n)));
      setDx(0);
      setDragging(false);
    },
    [last],
  );

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    startX.current = event.clientX;
    moved.current = false;
    setDragging(true);
    setDx(0);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const delta = event.clientX - startX.current;
    if (Math.abs(delta) > 6) moved.current = true;
    setDx(delta);
  };

  const endDrag = () => {
    if (!dragging) return;
    if (dx < -60) go(index + 1);
    else if (dx > 60) go(index - 1);
    else go(index);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight") {
      event.preventDefault();
      go(index + 1);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      go(index - 1);
    }
  };

  const screen = SCREENS[index];

  return (
    <div id="product" className="kl-wrap kl-product">
      <div className="kl-rv kl-product-caption" style={{ "--d": ".1s" } as CSSProperties} aria-live="polite">
        <span className="kl-product-title">{screen.title}</span>
        <span className="kl-product-sub">{screen.sub}</span>
      </div>
      <div
        className="kl-stage kl-fan"
        tabIndex={0}
        role="region"
        aria-roledescription="carousel"
        aria-label="Konverter console screens. Swipe, drag or use arrow keys."
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={endDrag}
        onKeyDown={onKeyDown}
      >
        {SCREENS.map((s, k) => {
          const offset = k - index + dx / 700;
          const distance = Math.abs(offset);
          const scale = Math.max(0.6, 1 - distance * 0.17);
          const rotate = Math.max(-28, Math.min(28, -offset * 16));
          const hidden = distance > 2.4;
          return (
            <button
              key={s.name}
              type="button"
              className={`kl-card${dragging ? " is-dragging" : ""}`}
              aria-label={`Show ${s.name} screen`}
              aria-current={k === index ? "true" : "false"}
              onClick={() => {
                if (moved.current) {
                  moved.current = false;
                  return;
                }
                go(k);
              }}
              style={{
                transform: `translateX(${offset * 58}%) scale(${scale}) rotateY(${rotate}deg)`,
                zIndex: Math.round(10 - distance * 2),
                opacity: hidden ? 0 : 1,
                pointerEvents: hidden ? "none" : undefined,
                filter: distance > 0.5 ? "saturate(.85) brightness(.97)" : "none",
              }}
            >
              <span className="kl-card-frame">
                <img src={s.src} alt={s.alt} draggable={false} />
              </span>
            </button>
          );
        })}
      </div>
      <div className="kl-rv kl-pager" style={{ "--d": ".7s" } as CSSProperties}>
        <button
          type="button"
          className="kl-arrow kl-arrow-prev"
          aria-label="Previous screen"
          disabled={index === 0}
          onClick={() => go(index - 1)}
        >
          <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M19 12H5M11 6l-6 6 6 6" />
          </svg>
        </button>
        <span className="kl-counter">
          {String(index + 1).padStart(2, "0")} / {String(SCREENS.length).padStart(2, "0")}
        </span>
        <button
          type="button"
          className="kl-arrow kl-arrow-next"
          aria-label="Next screen"
          disabled={index === last}
          onClick={() => go(index + 1)}
        >
          <ArrowRightIcon />
        </button>
      </div>
    </div>
  );
}

function TransformSection() {
  return (
    <section id="transform" aria-labelledby="tr-title" className="kl-transform">
      <div className="kl-wrap">
        <div className="kl-split-head">
          <h2 id="tr-title" className="kl-transform-title">
            From locked PDF to accessible, structured content.
          </h2>
          <p className="kl-transform-lead">
            Docling, vision-language models and OCR extract the text, tables and layout. Konverter
            rebuilds the heading structure, and reviewers confirm anything the model is unsure about.
          </p>
        </div>
        <div className="kl-flow">
          <div className="kl-flow-col">
            <span className="kl-flow-label">In · PDF</span>
            <div aria-hidden="true" className="kl-pdf">
              <span className="kl-pdf-title" />
              <span style={{ width: "94%" }} />
              <span style={{ width: "88%" }} />
              <span style={{ width: "91%" }} />
              <span className="kl-pdf-table" />
              <span style={{ width: "82%" }} />
              <span style={{ width: "90%" }} />
              <span className="kl-pdf-tag">PDF</span>
            </div>
            <span className="kl-flow-note">Up to 600+ pages</span>
          </div>
          <div className="kl-flow-arrow" aria-hidden="true">
            <svg className="kl-ico" viewBox="0 0 24 24">
              <path d="M4 12h16M14 6l6 6-6 6" />
            </svg>
          </div>
          <div className="kl-flow-col">
            <span className="kl-flow-label">Rebuilt · Structure + review</span>
            <div className="kl-tree">
              {TREE.map(({ tag, text, indent }) => (
                <div key={tag} className="kl-tree-row" style={{ marginLeft: indent }}>
                  <span className="kl-tree-tag">{tag}</span>
                  <span className="kl-tree-text">{text}</span>
                </div>
              ))}
              <div className="kl-tree-row is-flagged" style={{ marginLeft: 40 }}>
                <span style={{ display: "flex", gap: 10 }}>
                  <span className="kl-tree-tag">fn</span>
                  <span className="kl-tree-text">Footnote</span>
                </span>
                <span className="kl-tree-flag">
                  <span className="kl-square" />
                  Needs review
                </span>
              </div>
            </div>
            <span className="kl-flow-note">1,522 semantic blocks, scored for confidence</span>
          </div>
          <div className="kl-flow-arrow" aria-hidden="true">
            <svg className="kl-ico" viewBox="0 0 24 24">
              <path d="M4 12h16M14 6l6 6-6 6" />
            </svg>
          </div>
          <div className="kl-flow-col">
            <span className="kl-flow-label">Out · Publish</span>
            <div className="kl-outputs">
              <div className="kl-output">
                <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
                </svg>
                <span className="kl-output-text">
                  <strong>Accessible HTML</strong>
                  <span>Web publishing</span>
                </span>
              </div>
              <div className="kl-output">
                <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M8 4H7a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h1M16 4h1a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-1" />
                </svg>
                <span className="kl-output-text">
                  <strong>JSON</strong>
                  <span>AI systems, chatbots</span>
                </span>
              </div>
              <div className="kl-output">
                <svg className="kl-ico" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M3 12V4h8l10 10-8 8z" />
                  <circle cx="7.5" cy="8.5" r="1.5" />
                </svg>
                <span className="kl-output-text">
                  <strong>JSON-LD</strong>
                  <span>Search and AI discovery</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function WhySection() {
  return (
    <section aria-labelledby="why-title" className="kl-why">
      <div className="kl-wrap">
        <div className="kl-center-head">
          <p className="kl-eyebrow">Why Konverter</p>
          <h2 id="why-title" className="kl-h2">
            Built for documents that have to be right.
          </h2>
        </div>
        <div className="kl-why-grid">
          <article className="kl-why-card">
            <div aria-hidden="true" className="kl-why-visual kl-checks">
              {["Heading order", "Table headers", "Alt text"].map((label) => (
                <span key={label} className="kl-check">
                  <CheckIcon />
                  {label}
                </span>
              ))}
            </div>
            <h3 className="kl-why-title">Accessible HTML by design</h3>
            <p className="kl-why-body">
              Heading order, table headers and alt text are checked before accessible HTML is
              exported.
            </p>
          </article>
          <article className="kl-why-card">
            <div aria-hidden="true" className="kl-why-visual kl-bars">
              <span className="kl-bar-row">
                <span>Title</span>
                <span className="kl-bar-fill" style={{ width: "99%" }} />
              </span>
              <span className="kl-bar-row">
                <span>Publisher</span>
                <span className="kl-bar-fill" style={{ width: "98%" }} />
              </span>
              <span className="kl-bar-row">
                <span>Date</span>
                <span className="kl-bar-missing" />
              </span>
            </div>
            <h3 className="kl-why-title">People make the calls</h3>
            <p className="kl-why-body">
              Low-confidence items go to a reviewer, with the source page beside them.
            </p>
          </article>
          <article className="kl-why-card">
            <div aria-hidden="true" className="kl-code">
              {"{\n  "}
              <span className="kl-code-key">"@type"</span>
              {': "Report",\n  '}
              <span className="kl-code-key">"datePublished"</span>
              {': "2016-09",\n  '}
              <span className="kl-code-key">"inLanguage"</span>
              {': "en-AU"\n}'}
            </div>
            <h3 className="kl-why-title">Structured data, ready for AI</h3>
            <p className="kl-why-body">
              Clean JSON and schema.org JSON-LD for search, RAG and chatbots.
            </p>
          </article>
          <article className="kl-why-card">
            <div aria-hidden="true" className="kl-why-visual kl-events">
              {[
                ["Uploaded document", "04:59"],
                ["Started processing", "05:00"],
                ["Approved export", "05:41"],
              ].map(([label, time]) => (
                <span key={label} className="kl-event">
                  <span className="kl-event-dot" />
                  {label}
                  <span className="kl-event-time">{time}</span>
                </span>
              ))}
            </div>
            <h3 className="kl-why-title">A full audit trail</h3>
            <p className="kl-why-body">
              A tamper-evident audit log and role-based access for your team.
            </p>
          </article>
        </div>
      </div>
    </section>
  );
}

function ResultsSection() {
  return (
    <section aria-labelledby="res-title" className="kl-results">
      <div className="kl-wrap kl-results-grid">
        <div className="kl-results-head">
          <p className="kl-eyebrow">On real reports</p>
          <h2 id="res-title" className="kl-h2 kl-results-title">
            Proven on long legal reports.
          </h2>
        </div>
        <figure className="kl-figure">
          <figcaption>
            <span className="kl-figure-title">Report length</span>
            <span className="kl-figure-unit">pages</span>
          </figcaption>
          <div className="kl-lengths">
            <span aria-hidden="true" className="kl-length-rule" />
            <span className="kl-length-rule-label">400</span>
            {REPORT_LENGTHS.map(({ name, pages, share, color }) => (
              <div key={name} className="kl-length">
                <span>{name}</span>
                <div className="kl-length-bar">
                  <span style={{ width: `calc((100% - 44px) * ${share})`, background: color }} />
                  <span className="kl-figure-num">{pages}</span>
                </div>
              </div>
            ))}
          </div>
        </figure>
        <figure className="kl-figure" style={{ gap: 16 }}>
          <figcaption>
            <span className="kl-figure-title">Metadata confidence</span>
            <span className="kl-figure-unit">88-page report</span>
          </figcaption>
          {CONFIDENCE.map(({ field, pct }) => (
            <div key={field} className="kl-confidence">
              <span>{field}</span>
              {pct > 0 ? (
                <span className="kl-confidence-track">
                  <span style={{ width: `${pct}%` }} />
                </span>
              ) : (
                <span className="kl-confidence-track is-missing" />
              )}
              <span className={`kl-figure-num${pct > 0 ? "" : " is-missing"}`}>{pct}%</span>
            </div>
          ))}
          <p className="kl-confidence-note">
            <span aria-hidden="true" className="kl-square" />
            Not found, so sent to a reviewer.
          </p>
        </figure>
      </div>
    </section>
  );
}

/** Lights each step and grows the connecting line as the timeline scrolls into view. */
function EngageSection() {
  const listRef = useRef<HTMLOListElement>(null);
  const trackRef = useRef<HTMLSpanElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const list = listRef.current;
    const track = trackRef.current;
    const fill = fillRef.current;
    if (!list || !track || !fill) return;
    const steps = Array.from(list.querySelectorAll<HTMLElement>(".kl-step"));
    const media = window.matchMedia("(max-width: 860px)");

    const update = () => {
      const vertical = media.matches;
      const listBox = list.getBoundingClientRect();
      const dots = steps.map((step) => step.querySelector(".kl-tdot")!.getBoundingClientRect());
      const first = dots[0];
      const lastDot = dots[dots.length - 1];
      if (vertical) {
        track.style.width = "2px";
        track.style.height = `${lastDot.top - first.top}px`;
        track.style.top = `${first.top - listBox.top + 10}px`;
      } else {
        track.style.height = "2px";
        track.style.width = `${lastDot.left - first.left}px`;
        track.style.top = "9px";
      }
      let on = 0;
      steps.forEach((step, k) => {
        const lit = dots[k].top < window.innerHeight * (vertical ? 0.7 : 0.9 - k * 0.13);
        step.classList.toggle("kl-on", lit);
        if (lit) on = k;
      });
      const pct = steps[0].classList.contains("kl-on") ? (on / (steps.length - 1)) * 100 : 0;
      if (vertical) {
        fill.style.width = "100%";
        fill.style.height = `${pct}%`;
        fill.style.backgroundSize = `100% ${lastDot.top - first.top}px`;
      } else {
        fill.style.height = "100%";
        fill.style.width = `${pct}%`;
        fill.style.backgroundSize = `${lastDot.left - first.left}px 100%`;
      }
    };

    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <section id="engage" aria-labelledby="eng-title" className="kl-engage">
      <div className="kl-wrap">
        <div className="kl-engage-head">
          <p className="kl-eyebrow">Working with us</p>
          <h2 id="eng-title" className="kl-h2">
            A solution we set up with you, not a sign-up form.
          </h2>
        </div>
        <ol ref={listRef} className="kl-tl">
          <span ref={trackRef} className="kl-ttrack" aria-hidden="true">
            <span ref={fillRef} className="kl-tfill" />
          </span>
          {STEPS.map(({ title, body }, k) => (
            <li key={title} className="kl-step">
              <span className="kl-tdot" aria-hidden="true" />
              <span className="kl-step-num">{String(k + 1).padStart(2, "0")}</span>
              <span className="kl-step-title">{title}</span>
              <span className="kl-step-body">{body}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

type ChatMessage = { from: "bot" | "user"; text: string };

function FaqChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([{ from: "bot", text: FAQ_WELCOME }]);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, typing]);

  const ask = (question: string) => {
    const q = question.trim();
    if (!q || typing) return;
    setMessages((prev) => [...prev, { from: "user", text: q }]);
    setDraft("");
    setTyping(true);
    timer.current = window.setTimeout(() => {
      setTyping(false);
      setMessages((prev) => [...prev, { from: "bot", text: answerFaq(q) }]);
    }, 700);
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    ask(draft);
  };

  return (
    <section id="faq" aria-labelledby="faq-title" className="kl-faq">
      <div className="kl-wrap">
        <div className="kl-faq-head">
          <p className="kl-eyebrow">FAQ</p>
          <h2 id="faq-title" className="kl-h2">
            Questions? <span className="kl-faq-accent">Just ask.</span>
          </h2>
          <p className="kl-faq-lead">
            Pick a question or type your own. Answers come from the Komosion team’s FAQ; for
            anything else, request a demo.
          </p>
        </div>

        <div className="kl-chat">
          <div className="kl-chat-head">
            <span aria-hidden="true" className="kl-chat-avatar">
              <img src="/landing/komosion-mark-white.png" alt="" />
            </span>
            <span className="kl-chat-name">
              <strong>Ask Konverter</strong>
              <span>Answers from the Konverter FAQ</span>
            </span>
          </div>

          <div ref={logRef} className="kl-chat-log" role="log" aria-live="polite" aria-label="Conversation">
            {messages.map((message, k) => (
              <div key={k} className={`kl-msg kl-msg-${message.from}`}>
                {message.text}
              </div>
            ))}
            {typing ? (
              <div className="kl-msg-bot kl-typing" aria-label="Konverter is typing">
                <span />
                <span />
                <span />
              </div>
            ) : null}
          </div>

          <div className="kl-chat-foot">
            <div className="kl-chips" aria-label="Suggested questions">
              {FAQ_ITEMS.map((item) => (
                <button key={item.q} type="button" className="kl-qchip" onClick={() => ask(item.q)}>
                  {item.q}
                </button>
              ))}
            </div>
            <form className="kl-ask-form" onSubmit={onSubmit}>
              <label htmlFor="kl-ask" className="kl-sr-only">
                Ask a question about Konverter
              </label>
              <input
                id="kl-ask"
                className="kl-ask"
                type="text"
                placeholder="Ask about Konverter…"
                autoComplete="off"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
              <button type="submit" aria-label="Send question" className="kl-btn kl-btn-navy kl-ask-send">
                <ArrowRightIcon />
              </button>
            </form>
          </div>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="kl-footer">
      <div className="kl-wrap kl-footer-logo">
        <a href="https://www.komosion.com" aria-label="Komosion home">
          <img src="/landing/komosion-wordmark-white.png" alt="Komosion" />
        </a>
      </div>
      <div className="kl-wrap kl-footer-cols">
        <div className="kl-footer-col">
          <h2 className="kl-footer-heading">Contact</h2>
          <ul className="kl-contact">
            <li>
              <span aria-hidden="true" className="kl-contact-icon">
                <svg viewBox="0 0 24 24">
                  <path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z" />
                </svg>
              </span>
              <span>Sydney, Brisbane, Melbourne, Ho Chi Minh City</span>
            </li>
            <li>
              <span aria-hidden="true" className="kl-contact-icon">
                <svg viewBox="0 0 24 24">
                  <path d="M20 15.5c-1.2 0-2.4-.2-3.6-.6a1 1 0 0 0-1 .25l-2.2 2.2a15.1 15.1 0 0 1-6.6-6.6l2.2-2.2a1 1 0 0 0 .25-1A11.4 11.4 0 0 1 8.5 4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1 17 17 0 0 0 17 17 1 1 0 0 0 1-1v-3.5a1 1 0 0 0-1-1z" />
                </svg>
              </span>
              <a href="tel:+61419751798" className="kl-plain">
                +61 (0)419 751 798
              </a>
            </li>
            <li>
              <span aria-hidden="true" className="kl-contact-icon">
                <svg viewBox="0 0 24 24">
                  <path d="M3 5h18a1 1 0 0 1 1 1v.4l-10 6.2L2 6.4V6a1 1 0 0 1 1-1zm-1 3.7 9.5 5.9a1 1 0 0 0 1 0L22 8.7V18a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z" />
                </svg>
              </span>
              <a href="mailto:info@komosion.com" className="kl-plain">
                info@komosion.com
              </a>
            </li>
          </ul>
        </div>
        <div className="kl-footer-col">
          <h2 className="kl-footer-heading">Stay in touch</h2>
          <p className="kl-footer-note">AI insights for Australian leaders, once a month.</p>
          <div className="kl-footer-social">
            <a href="https://www.komosion.com" className="kl-btn kl-btn-ghost kl-btn-subscribe">
              Subscribe
            </a>
            <a
              href="https://www.linkedin.com/company/komosion/"
              aria-label="Komosion on LinkedIn"
              className="kl-btn kl-btn-ghost kl-btn-linkedin"
            >
              in
            </a>
          </div>
        </div>
      </div>
      <div className="kl-footer-legal">
        <div className="kl-wrap">
          <span>KOMOSION © {new Date().getFullYear()} All rights reserved</span>
          <span aria-hidden="true">|</span>
          <a href="https://www.komosion.com">Privacy Policy</a>
          <span aria-hidden="true">|</span>
          <a href="https://www.komosion.com">Sitemap</a>
        </div>
      </div>
    </footer>
  );
}

export function LandingPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  useScrollReveal(rootRef);

  useEffect(() => {
    const previous = document.title;
    document.title = "Konverter by Komosion | Convert PDFs to Accessible HTML & JSON-LD";
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <div ref={rootRef} className="kl">
      <Header />

      <main>
        <section id="top" aria-labelledby="hero-title" className="kl-hero">
          <Hero />
          <div className="kl-land">
            <svg aria-hidden="true" className="kl-land-lines" viewBox="0 0 1440 600" preserveAspectRatio="none">
              <polyline
                points="0,420 160,380 300,405 460,320 600,345 760,250 900,275 1060,170 1220,195 1440,110"
                fill="none"
                stroke="#FFFFFF"
                strokeOpacity=".22"
                strokeWidth="1.5"
              />
              <polyline
                points="0,500 200,470 360,485 540,420 700,440 880,370 1040,385 1220,310 1440,290"
                fill="none"
                stroke="#FFFFFF"
                strokeOpacity=".14"
                strokeWidth="1.5"
              />
              <circle cx="1060" cy="170" r="4" fill="#FFFFFF" fillOpacity=".6" />
            </svg>
            <ScreenCarousel />
          </div>
        </section>

        <section aria-label="About Konverter" className="kl-intro">
          <div className="kl-wrap">
            <span aria-hidden="true" className="kl-rv kl-pop kl-intro-mark">
              <img src="/landing/komosion-mark-navy.png" alt="" />
            </span>
            <p className="kl-rv kl-intro-text" style={{ "--d": ".15s" } as CSSProperties}>
              Most legal organisations have <span className="kl-light">digitised</span> their
              reports. Very few have <span className="kl-sweep">transformed</span> them. Konverter
              closes that gap, one reviewed document at a time.
            </p>
          </div>
        </section>

        <section aria-label="Konverter in numbers" className="kl-stats-section">
          <div className="kl-wrap kl-stats">
            {STATS.map(({ value, of, label, tone }) => (
              <div key={label} className={`kl-stat ${tone}`}>
                <span className="kl-stat-value">
                  {value}
                  {of ? <span className="kl-stat-of">{of}</span> : null}
                </span>
                <span className="kl-stat-label">{label}</span>
              </div>
            ))}
          </div>
        </section>

        <TransformSection />
        <WhySection />
        <ResultsSection />
        <EngageSection />
        <FaqChat />

        <section aria-labelledby="cta-title" className="kl-cta">
          <div className="kl-wrap">
            <div className="kl-cta-panel">
              <h2 id="cta-title" className="kl-cta-title">
                See Konverter convert your own reports.
              </h2>
              <div className="kl-cta-side">
                <p className="kl-cta-text">
                  Book a walkthrough with the Komosion team using a PDF you choose, and see the
                  accessible HTML and JSON-LD it produces.
                </p>
                <div className="kl-cta-buttons">
                  <a href={DEMO_URL} className="kl-btn kl-btn-white kl-btn-cta">
                    Request a demo <span aria-hidden="true">→</span>
                  </a>
                  <Link to={LOGIN_PATH} className="kl-btn kl-btn-ghost kl-btn-cta">
                    Client login
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <Footer />

      <div className="kl-mbar" role="region" aria-label="Quick actions">
        <div className="kl-mbar-inner">
          <Link to={LOGIN_PATH} className="kl-mbar-login">
            <LockIcon />
            Client login
          </Link>
          <a href={DEMO_URL} className="kl-mbar-demo">
            Request a demo
          </a>
        </div>
      </div>
    </div>
  );
}

export default LandingPage;
