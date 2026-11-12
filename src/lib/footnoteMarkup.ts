import type { ReviewType, StyleRun } from "../types/konverter";

/**
 * The text-style editor is a plain textarea, so italic and bold are written
 * inline: *italic*, **bold**, ***both***. A literal `*` or `\` is written
 * `\*` / `\\`. A marker with no partner stays literal text, so a stray
 * asterisk never silently styles the rest of the block.
 */

/** Review types whose text can carry italic/bold ranges. Keep this in sync
 * with backend/app/text_styles.py's STYLE_CAPABLE_LABELS. */
export const STYLE_CAPABLE_TYPES: ReadonlySet<ReviewType> = new Set([
  "footnote",
  "text",
]);

export function supportsTextStyles(type: ReviewType): boolean {
  return STYLE_CAPABLE_TYPES.has(type);
}

type Token =
  | { kind: "text"; value: string; sources: number[] }
  | {
      kind: "mark";
      style: "italic" | "bold";
      raw: string;
      source: number;
      paired: boolean;
    };

type Style = "italic" | "bold";

interface Parsed {
  text: string;
  styles: StyleRun[];
  /** For each character of `text`, where it starts in the markup. */
  sources: number[];
}

/** Markup for `text` plus, for each character, the [start, end) range of
 * markup that represents it (an escaped `*` is two markup characters).
 * Markers are written as toggles wherever the style changes, so a boundary
 * never carries more than `***`. */
function write(text: string, styles: StyleRun[]) {
  const italic = new Array<boolean>(text.length).fill(false);
  const bold = new Array<boolean>(text.length).fill(false);
  for (const run of styles) {
    for (let i = Math.max(run.start, 0); i < Math.min(run.end, text.length); i += 1) {
      italic[i] ||= run.italic;
      bold[i] ||= run.bold;
    }
  }
  const starts: number[] = [];
  const ends: number[] = [];
  let markup = "";
  let wasItalic = false;
  let wasBold = false;
  const transition = (nowBold: boolean, nowItalic: boolean) => {
    if (nowBold !== wasBold) markup += "**";
    if (nowItalic !== wasItalic) markup += "*";
    wasBold = nowBold;
    wasItalic = nowItalic;
  };
  for (let i = 0; i < text.length; i += 1) {
    transition(bold[i], italic[i]);
    starts[i] = markup.length;
    markup += text[i] === "*" || text[i] === "\\" ? `\\${text[i]}` : text[i];
    ends[i] = markup.length;
  }
  transition(false, false);
  return { markup, starts, ends };
}

export function toMarkup(text: string, styles: StyleRun[] = []): string {
  return write(text, styles).markup;
}

function tokenize(markup: string): Token[] {
  const tokens: Token[] = [];
  let buffer = "";
  let sources: number[] = [];
  const flush = () => {
    if (buffer) tokens.push({ kind: "text", value: buffer, sources });
    buffer = "";
    sources = [];
  };
  for (let i = 0; i < markup.length; i += 1) {
    const char = markup[i];
    if (char === "\\" && (markup[i + 1] === "*" || markup[i + 1] === "\\")) {
      buffer += markup[i + 1];
      sources.push(i);
      i += 1;
    } else if (char === "*") {
      let length = 1;
      while (markup[i + length] === "*") length += 1;
      if (length > 3) {
        for (let k = 0; k < length; k += 1) {
          buffer += "*";
          sources.push(i + k);
        }
        i += length - 1;
        continue;
      }
      flush();
      if (length >= 2)
        tokens.push({
          kind: "mark",
          style: "bold",
          raw: "**",
          source: i,
          paired: false,
        });
      if (length !== 2)
        tokens.push({
          kind: "mark",
          style: "italic",
          raw: "*",
          source: i + (length === 3 ? 2 : 0),
          paired: false,
        });
      i += length - 1;
    } else {
      buffer += char;
      sources.push(i);
    }
  }
  flush();
  return tokens;
}

function parse(markup: string): Parsed {
  const tokens = tokenize(markup);
  const open: Partial<Record<Style, Token & { kind: "mark" }>> = {};
  for (const token of tokens) {
    if (token.kind !== "mark") continue;
    const opener = open[token.style];
    if (opener) {
      opener.paired = true;
      token.paired = true;
      delete open[token.style];
    } else {
      open[token.style] = token;
    }
  }

  let text = "";
  const sources: number[] = [];
  const styles: StyleRun[] = [];
  let italic = false;
  let bold = false;
  let runStart = 0;
  const closeRun = () => {
    if ((italic || bold) && text.length > runStart)
      styles.push({ start: runStart, end: text.length, italic, bold });
    runStart = text.length;
  };
  for (const token of tokens) {
    if (token.kind === "text") {
      text += token.value;
      sources.push(...token.sources);
    } else if (!token.paired) {
      for (let k = 0; k < token.raw.length; k += 1) sources.push(token.source + k);
      text += token.raw;
    } else {
      closeRun();
      if (token.style === "italic") italic = !italic;
      else bold = !bold;
    }
  }
  closeRun();
  return { text, styles, sources };
}

export function fromMarkup(markup: string): { text: string; styles: StyleRun[] } {
  const { text, styles } = parse(markup);
  return { text, styles };
}

/** What the API takes for a style-capable block: the text trimmed, and
 * ranges relative to that trimmed text. */
export function styledTextPayload(markup: string): {
  correctedText: string;
  correctedStyles: StyleRun[];
} {
  const { text, styles } = parse(markup);
  const lead = text.length - text.trimStart().length;
  const trimmed = text.trim();
  const correctedStyles: StyleRun[] = [];
  for (const run of styles) {
    const start = Math.max(run.start - lead, 0);
    const end = Math.min(run.end - lead, trimmed.length);
    if (end > start) correctedStyles.push({ ...run, start, end });
  }
  return { correctedText: trimmed, correctedStyles };
}

/** Backwards-compatible name for the same payload helper. */
export const footnotePayload = styledTextPayload;

/** Toggle italic or bold over the selected part of the markup: removed if
 * the whole selection already has it, otherwise applied. Works on the parsed
 * ranges, so a selection that already contains markers can't mispair them.
 * Returns the new markup and where the same characters now sit in it. */
export function toggleStyle(
  markup: string,
  selectionStart: number,
  selectionEnd: number,
  style: Style,
): { markup: string; selectionStart: number; selectionEnd: number } {
  const { text, styles, sources } = parse(markup);
  const countBefore = (position: number) =>
    sources.filter((source) => source < position).length;
  const from = countBefore(selectionStart);
  const to = countBefore(selectionEnd);
  if (to <= from) return { markup, selectionStart, selectionEnd };

  const italic = new Array<boolean>(text.length).fill(false);
  const bold = new Array<boolean>(text.length).fill(false);
  for (const run of styles) {
    for (let i = run.start; i < run.end; i += 1) {
      italic[i] = run.italic;
      bold[i] = run.bold;
    }
  }
  const flags = style === "italic" ? italic : bold;
  let allStyled = true;
  for (let i = from; i < to; i += 1) allStyled &&= flags[i];
  for (let i = from; i < to; i += 1) flags[i] = !allStyled;

  const next: StyleRun[] = [];
  for (let i = 0; i < text.length; i += 1) {
    if (!italic[i] && !bold[i]) continue;
    const last = next[next.length - 1];
    if (last && last.end === i && last.italic === italic[i] && last.bold === bold[i])
      last.end = i + 1;
    else next.push({ start: i, end: i + 1, italic: italic[i], bold: bold[i] });
  }

  const written = write(text, next);
  return {
    markup: written.markup,
    selectionStart: written.starts[from],
    selectionEnd: written.ends[to - 1],
  };
}
