import type { StyleRun } from "../types/konverter";

/**
 * The review editor shows italic/bold as real formatting. The API still takes
 * and returns plain text plus style ranges, so this is the only place that
 * translates between those and the editor's DOM.
 */

export interface RichValue {
  text: string;
  styles: StyleRun[];
}

/** Text and ranges as the editor shows them: trimmed, with the ranges
 * rebased onto the trimmed text. Detected ranges already index into the
 * trimmed text, so for those this only guards against stray whitespace. */
export function richValue(text: string, styles: StyleRun[] = []): RichValue {
  const lead = text.length - text.trimStart().length;
  const trimmed = text.trim();
  return { text: trimmed, styles: rebase(styles, lead, trimmed.length) };
}

function rebase(styles: StyleRun[], offset: number, length: number): StyleRun[] {
  const out: StyleRun[] = [];
  for (const run of styles) {
    const start = Math.max(run.start - offset, 0);
    const end = Math.min(run.end - offset, length);
    if (end > start) out.push({ ...run, start, end });
  }
  return out;
}

/** What a save sends: the text trimmed, ranges relative to that text. */
export function richPayload(value: RichValue): {
  correctedText: string;
  correctedStyles: StyleRun[];
} {
  const { text, styles } = richValue(value.text, value.styles);
  return { correctedText: text, correctedStyles: styles };
}

/** Fill `root` with `value`: plain text nodes, wrapped in <em>/<strong>
 * where a run covers them. Newlines stay as "\n" (the editor is pre-wrap). */
export function renderRich(root: HTMLElement, value: RichValue): void {
  root.replaceChildren();
  const { text, styles } = value;
  const cuts = new Set<number>([0, text.length]);
  for (const run of styles) {
    cuts.add(Math.max(run.start, 0));
    cuts.add(Math.min(run.end, text.length));
  }
  const points = [...cuts].sort((a, b) => a - b);
  for (let i = 0; i < points.length - 1; i += 1) {
    const [start, end] = [points[i], points[i + 1]];
    if (end <= start) continue;
    const covering = styles.filter((run) => run.start <= start && run.end >= end);
    let node: Node = document.createTextNode(text.slice(start, end));
    if (covering.some((run) => run.italic)) node = wrap("em", node);
    if (covering.some((run) => run.bold)) node = wrap("strong", node);
    root.appendChild(node);
  }
}

function wrap(tag: "em" | "strong", child: Node): HTMLElement {
  const element = document.createElement(tag);
  element.appendChild(child);
  return element;
}

const BLOCK_TAGS = new Set(["DIV", "P", "LI", "BLOCKQUOTE", "H1", "H2", "H3", "H4", "H5", "H6"]);

function isBold(element: HTMLElement, inherited: boolean): boolean {
  const weight = element.style?.fontWeight;
  if (weight) {
    if (weight === "normal") return false;
    return weight === "bold" || weight === "bolder" || Number.parseInt(weight, 10) >= 600;
  }
  return inherited || element.tagName === "B" || element.tagName === "STRONG";
}

function isItalic(element: HTMLElement, inherited: boolean): boolean {
  const fontStyle = element.style?.fontStyle;
  if (fontStyle) return fontStyle === "italic" || fontStyle === "oblique";
  return inherited || element.tagName === "I" || element.tagName === "EM";
}

/** Read text and ranges back out of the editor. Browsers disagree about the
 * markup they produce (<b> vs <strong>, styled spans, <div>/<br> for line
 * breaks), so all of those are folded into the same result. */
export function readRich(root: HTMLElement): RichValue {
  let text = "";
  const styles: StyleRun[] = [];

  const push = (chunk: string, italic: boolean, bold: boolean) => {
    if (!chunk) return;
    const start = text.length;
    text += chunk;
    if (!italic && !bold) return;
    const last = styles[styles.length - 1];
    if (last && last.end === start && last.italic === italic && last.bold === bold) {
      last.end = text.length;
    } else {
      styles.push({ start, end: text.length, italic, bold });
    }
  };

  const walk = (node: Node, italic: boolean, bold: boolean) => {
    if (node.nodeType === Node.TEXT_NODE) {
      push(node.textContent ?? "", italic, bold);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const element = node as HTMLElement;
    if (element.tagName === "BR") {
      push("\n", false, false);
      return;
    }
    const block = BLOCK_TAGS.has(element.tagName);
    if (block && text && !text.endsWith("\n")) push("\n", false, false);
    const nextItalic = isItalic(element, italic);
    const nextBold = isBold(element, bold);
    element.childNodes.forEach((child) => walk(child, nextItalic, nextBold));
  };

  root.childNodes.forEach((child) => walk(child, false, false));
  return { text, styles };
}
