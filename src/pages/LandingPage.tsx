import {
  BadgeCheck,
  ClipboardCheck,
  Database,
  ExternalLink,
  FileCheck2,
  Search,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

const VLRC_LINKS = [
  { label: "About us", href: "https://www.lawreform.vic.gov.au/about-us/" },
  { label: "All projects", href: "https://www.lawreform.vic.gov.au/all-projects/" },
  {
    label: "Publications",
    href: "https://www.lawreform.vic.gov.au/publications-and-media/publications/",
  },
  { label: "Contact us", href: "https://www.lawreform.vic.gov.au/contact-us/" },
];

const TRUST_POINTS = [
  "No technical skills needed",
  "Every report checked by a person",
  "Meets accessibility standards",
];

const FEATURES = [
  {
    icon: UploadCloud,
    title: "Reads the PDF for you",
    body: "Upload a report and Konverter automatically pulls out the headings, paragraphs, tables and figures — no retyping or copy-pasting.",
  },
  {
    icon: ClipboardCheck,
    title: "Flags anything it's unsure about",
    body: "If the system isn't confident it read something correctly, it doesn't guess — it puts that item in front of a reviewer, next to the original PDF page, before it can be published.",
  },
  {
    icon: FileCheck2,
    title: "Nothing publishes without sign-off",
    body: "A person always reviews the flagged items and confirms the report's details before it goes live. The computer never has the final say.",
  },
  {
    icon: ShieldCheck,
    title: "Every action is logged",
    body: "Who reviewed what, and when, is recorded in a tamper-evident log — so there's always a clear record behind every published report.",
  },
];

const STEPS = [
  {
    label: "Upload",
    title: "Add your PDF",
    body: "Drop in a report. Konverter reads it automatically and pulls out the headings, paragraphs, tables and figures.",
  },
  {
    label: "Review",
    title: "Check what it's unsure about",
    body: "Anything the system didn't read confidently is queued for you to check against the original page — accept it, or fix it.",
  },
  {
    label: "Metadata",
    title: "Confirm the details",
    body: "Confirm the title, date, publisher and other basic details, so the report is described correctly wherever it's published.",
  },
  {
    label: "Preview & publish",
    title: "Check it, then export",
    body: "Preview exactly how the finished report will look, then approve it to generate the exports below.",
  },
];

const EXPORTS = [
  {
    icon: FileCheck2,
    title: "Accessible report",
    format: "HTML web page",
    body: "A web page version of your report that works properly with screen readers and keyboard navigation, so people with disabilities can read it just as easily as anyone else.",
    use: "Publish it on your website",
  },
  {
    icon: Search,
    title: "Search-friendly summary",
    format: "JSON-LD",
    body: "An invisible summary of the report's title, author, date and topics, written in a format search engines understand — so your report is found and shown correctly in search results.",
    use: "Helps people find the report",
  },
  {
    icon: Database,
    title: "Full data export",
    format: "Structured JSON",
    body: "Every paragraph, table and detail from the report, organised into a single file that other websites, archives or systems can plug straight into.",
    use: "Reuse it in other systems",
  },
];

const FAQ = [
  {
    question: "Do I need any technical skills to use Konverter?",
    answer:
      "No. If you can use a web browser, you can use Konverter — upload a PDF and the pipeline takes care of the extraction. Reviewing flagged items is just reading a page and clicking accept or correct.",
  },
  {
    question: "What happens if it reads something wrong?",
    answer:
      "Anything the system isn't confident about is automatically set aside for a reviewer to check next to the original PDF page, so mistakes get caught before the report is published — not after.",
  },
  {
    question: "What does “accessible” actually mean here?",
    answer:
      "It means the published report works properly with screen readers, keyboard-only navigation and other assistive technology — not just that it looks like a normal web page.",
  },
  {
    question: "Is the original PDF kept?",
    answer:
      "Yes. The source PDF stays attached to the record, and every reviewed item links back to the exact page it came from, so you can always check the original.",
  },
];

function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={`reveal ${visible ? "is-visible" : ""} ${className}`}>
      {children}
    </div>
  );
}

export function LandingPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(0);

  return (
    <div className="site-shell">
      <a className="skip-link" href="#landing-main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header-inner">
          <Link className="site-brand" to="/" aria-label="Konverter home">
            <span className="site-brand-mark">
              <img src="/komosion_logo.png" alt="Komosion" />
            </span>
            <span>
              <strong>Konverter</strong>
              <small>Accessible publishing workspace</small>
            </span>
          </Link>
          <nav className="site-nav" aria-label="Primary">
            <a href="#how-it-works">How it works</a>
            <a href="#what-you-get">What you get</a>
            <a href="#faq">FAQ</a>
            <Link className="button button-primary" to="/login">
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main id="landing-main">
        <section className="landing-hero">
          <div className="page-container landing-hero-inner">
            <div className="landing-hero-copy">
              <span className="eyebrow">Victorian Law Reform Commission</span>
              <h1>Make your reports accessible to everyone — without the manual work</h1>
              <p className="landing-hero-lead">
                Konverter turns your PDF reports into accessible web pages that
                anyone can read, including people using screen readers. A real
                person always checks the result before anything is published —
                you don&rsquo;t need any technical skills to use it.
              </p>
              <div className="landing-cta-row">
                <Link className="button button-primary" to="/login">
                  Sign in to get started
                </Link>
                <a className="button button-secondary" href="#how-it-works">
                  See how it works
                </a>
              </div>
              <ul className="landing-trust-row">
                {TRUST_POINTS.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>

            <div className="landing-hero-visual" aria-hidden="true">
              <div className="hero-mock-card">
                <div className="hero-mock-card-head">
                  <span className="hero-mock-dot" />
                  <span className="hero-mock-dot" />
                  <span className="hero-mock-dot" />
                  <span className="hero-mock-filename">annual-report.pdf</span>
                </div>

                <div className="hero-mock-page">
                  <div className="hero-mock-region region-title">
                    <span className="hero-mock-region-label">Title</span>
                    <div className="hero-mock-block" />
                  </div>

                  <div className="hero-mock-region region-paragraph">
                    <span className="hero-mock-region-label">Paragraph</span>
                    <div className="hero-mock-line w-100" />
                    <div className="hero-mock-line w-90" />
                    <div className="hero-mock-line w-70" />
                  </div>

                  <div className="hero-mock-region region-table">
                    <span className="hero-mock-region-label">Table</span>
                    <div className="hero-mock-grid">
                      <span />
                      <span />
                      <span />
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>

                  <div className="hero-mock-region region-flag">
                    <span className="hero-mock-region-label region-label-flag">
                      Needs review
                    </span>
                    <div className="hero-mock-line w-90" />
                    <div className="hero-mock-line w-60" />
                  </div>
                </div>
              </div>

              <div className="hero-mock-badge">
                <BadgeCheck aria-hidden="true" />
                <span>Reviewed &amp; approved</span>
              </div>
            </div>
          </div>
        </section>

        <section id="what-it-does" className="landing-section">
          <Reveal className="page-container">
            <div className="landing-section-head">
              <span className="eyebrow">What it does</span>
              <h2>A computer does the reading. A person makes the call.</h2>
              <p>
                Konverter doesn&rsquo;t just convert a file from one format to
                another — it reads the report, tells you what it&rsquo;s
                unsure about, and waits for a person to confirm it before
                anything is published.
              </p>
            </div>
            <div className="landing-features">
              {FEATURES.map(({ icon: Icon, title, body }) => (
                <div className="feature-card" key={title}>
                  <div className="feature-card-icon">
                    <Icon aria-hidden="true" />
                  </div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        <section id="how-it-works" className="landing-section landing-section-alt">
          <Reveal className="page-container">
            <div className="landing-section-head">
              <span className="eyebrow">How it works</span>
              <h2>Four simple stages, start to finish</h2>
              <p>
                Every report moves through the same four stages, from the raw
                PDF you upload to the finished, published report.
              </p>
            </div>
            <div className="landing-steps">
              {STEPS.map((step, index) => (
                <div className="step-card" key={step.label}>
                  <span className="step-card-num" aria-hidden="true">
                    {index + 1}
                  </span>
                  <span className="step-card-label">{step.label}</span>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        <section id="what-you-get" className="landing-section">
          <Reveal className="page-container">
            <div className="landing-section-head">
              <span className="eyebrow">What you get</span>
              <h2>Three files, one approval</h2>
              <p>
                When you approve a report, Konverter generates three exports
                automatically. Here&rsquo;s what each one is actually for.
              </p>
            </div>
            <div className="landing-exports">
              {EXPORTS.map(({ icon: Icon, title, format, body, use }) => (
                <div className="export-card" key={title}>
                  <div className="export-card-head">
                    <div className="feature-card-icon">
                      <Icon aria-hidden="true" />
                    </div>
                    <span className="export-card-format">{format}</span>
                  </div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                  <span className="export-card-use">{use}</span>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        <section id="faq" className="landing-section landing-section-alt">
          <Reveal className="page-container landing-faq-inner">
            <div className="landing-section-head">
              <span className="eyebrow">Questions</span>
              <h2>Common questions</h2>
              <p>
                New to Konverter? Here&rsquo;s what people usually want to
                know before they start.
              </p>
            </div>
            <div className="landing-faq-list">
              {FAQ.map((item, index) => {
                const isOpen = openFaq === index;
                return (
                  <div className="faq-item" key={item.question}>
                    <button
                      type="button"
                      className="faq-question"
                      aria-expanded={isOpen}
                      aria-controls={`faq-answer-${index}`}
                      onClick={() => setOpenFaq(isOpen ? null : index)}
                    >
                      <span>{item.question}</span>
                      <span className="faq-toggle" aria-hidden="true">
                        {isOpen ? "−" : "+"}
                      </span>
                    </button>
                    {isOpen && (
                      <p className="faq-answer" id={`faq-answer-${index}`}>
                        {item.answer}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </Reveal>
        </section>

        <section className="landing-cta-band">
          <Reveal className="page-container landing-cta-band-inner">
            <div>
              <h2>Ready to review your first report?</h2>
              <p>Sign in to your Konverter account to start uploading and reviewing.</p>
            </div>
            <Link className="button button-primary" to="/login">
              Sign in
            </Link>
          </Reveal>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-footer-inner">
          <div>
            <Link className="site-brand" to="/" aria-label="Konverter home">
              <span className="site-brand-mark">
                <img src="/komosion_logo.png" alt="Komosion" />
              </span>
              <span>
                <strong>Konverter</strong>
                <small>Accessible publishing workspace</small>
              </span>
            </Link>
            <p>
              Konverter is the Victorian Law Reform Commission&rsquo;s internal
              workspace for converting and reviewing accessible publications
              before they&rsquo;re published.
            </p>
          </div>

          <div>
            <span className="footer-col-title">On this page</span>
            <ul className="footer-col-links">
              <li>
                <a href="#what-it-does">What it does</a>
              </li>
              <li>
                <a href="#how-it-works">How it works</a>
              </li>
              <li>
                <a href="#what-you-get">What you get</a>
              </li>
              <li>
                <a href="#faq">FAQ</a>
              </li>
            </ul>
          </div>

          <div>
            <span className="footer-col-title">Victorian Law Reform Commission</span>
            <ul className="footer-col-links">
              {VLRC_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <a href={href} target="_blank" rel="noreferrer">
                    {label}
                    <ExternalLink aria-hidden="true" />
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <span className="footer-col-title">Konverter</span>
            <ul className="footer-col-links">
              <li>
                <Link to="/login">Sign in</Link>
              </li>
            </ul>
          </div>
        </div>

        <div className="page-container site-footer-bottom">
          <span>© {new Date().getFullYear()} Komosion</span>
          <Link to="/login">Sign in to Konverter →</Link>
        </div>
      </footer>
    </div>
  );
}
