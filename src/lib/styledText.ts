import type { JSONContent } from "@tiptap/core";
import type { ReviewType, StyleRun } from "../types/konverter";

/** Review types whose text can carry italic/bold ranges. Keep this in sync
 * with backend/app/text_styles.py's STYLE_CAPABLE_LABELS. */
export const STYLE_CAPABLE_TYPES: ReadonlySet<ReviewType> = new Set([
  "footnote",
  "text",
]);

export function supportsTextStyles(type: ReviewType): boolean {
  return STYLE_CAPABLE_TYPES.has(type);
}

/** A style-capable block's text plus the italic/bold ranges over it. */
export interface StyledText {
  text: string;
  styles: StyleRun[];
}

/**
 * The rich-text editor works on a ProseMirror document, but the API still
 * takes plain text plus ranges (`correctedText` / `correctedStyles`). These
 * two functions are the only place that translates between them.
 *
 * Paragraphs are separated by a blank line (`\n\n`); a single newline is a
 * hard break. That is exactly how the old textarea behaved, so text that
 * round-trips through the editor comes back byte-for-byte unchanged.
 */

/** Per-character italic/bold flags, so overlapping ranges can't double-wrap. */
function markFlags(text: string, styles: StyleRun[]) {
  const italic = new Uint8Array(text.length);
  const bold = new Uint8Array(text.length);
  const italicDelta = new Int32Array(text.length + 1);
  const boldDelta = new Int32Array(text.length + 1);

  for (const run of styles) {
    const start = Math.max(0, Math.min(text.length, Math.trunc(run.start)));
    const end = Math.max(0, Math.min(text.length, Math.trunc(run.end)));
    if (end <= start) continue;
    if (run.italic) {
      italicDelta[start] += 1;
      italicDelta[end] -= 1;
    }
    if (run.bold) {
      boldDelta[start] += 1;
      boldDelta[end] -= 1;
    }
  }

  let activeItalic = 0;
  let activeBold = 0;
  for (let index = 0; index < text.length; index += 1) {
    activeItalic += italicDelta[index];
    activeBold += boldDelta[index];
    italic[index] = activeItalic > 0 ? 1 : 0;
    bold[index] = activeBold > 0 ? 1 : 0;
  }
  return { italic, bold };
}

/** Plain text + ranges -> the ProseMirror JSON document the editor loads. */
export function styledTextToDoc({ text, styles }: StyledText): JSONContent {
  const { italic, bold } = markFlags(text, styles);
  const paragraphs: JSONContent[] = [];
  let inline: JSONContent[] = [];
  let run: { text: string; italic: boolean; bold: boolean } | null = null;

  const flushRun = () => {
    if (!run || !run.text) {
      run = null;
      return;
    }
    const marks = [
      ...(run.italic ? [{ type: "italic" }] : []),
      ...(run.bold ? [{ type: "bold" }] : []),
    ];
    inline.push({
      type: "text",
      text: run.text,
      ...(marks.length ? { marks } : {}),
    });
    run = null;
  };
  const endParagraph = () => {
    flushRun();
    paragraphs.push({ type: "paragraph", content: inline });
    inline = [];
  };

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === "\n") {
      flushRun();
      if (text[index + 1] === "\n") {
        endParagraph();
        index += 1;
      } else {
        inline.push({ type: "hardBreak" });
      }
      continue;
    }
    const isItalic = italic[index] === 1;
    const isBold = bold[index] === 1;
    if (!run || run.italic !== isItalic || run.bold !== isBold) {
      flushRun();
      run = { text: "", italic: isItalic, bold: isBold };
    }
    run.text += character;
  }
  endParagraph();
  return { type: "doc", content: paragraphs };
}

/** The ProseMirror JSON document -> plain text + merged style ranges. */
export function docToStyledText(doc: JSONContent): StyledText {
  const styles: StyleRun[] = [];
  let text = "";

  const append = (value: string, italic: boolean, bold: boolean) => {
    if (!value) return;
    const start = text.length;
    text += value;
    // Plain text carries no range; leaving it out keeps the payload small and
    // stops an unstyled gap from being merged into a neighbouring style.
    if (!italic && !bold) return;
    const last = styles[styles.length - 1];
    if (last && last.end === start && last.italic === italic && last.bold === bold) {
      last.end = text.length;
    } else {
      styles.push({ start, end: text.length, italic, bold });
    }
  };

  const blocks = doc.content ?? [];
  blocks.forEach((block, blockIndex) => {
    if (blockIndex > 0) text += "\n\n";
    for (const node of block.content ?? []) {
      if (node.type === "text") {
        const marks = node.marks ?? [];
        append(
          node.text ?? "",
          marks.some((mark) => mark.type === "italic"),
          marks.some((mark) => mark.type === "bold"),
        );
      } else if (node.type === "hardBreak") {
        text += "\n";
      }
    }
  });

  return { text, styles };
}

/** True when two values describe the same document (avoids cursor jumps). */
export function sameStyledText(left: StyledText, right: StyledText): boolean {
  if (left.text !== right.text) return false;
  if (left.styles.length !== right.styles.length) return false;
  return left.styles.every((run, index) => {
    const other = right.styles[index];
    return (
      run.start === other.start &&
      run.end === other.end &&
      run.italic === other.italic &&
      run.bold === other.bold
    );
  });
}

/** What the API takes for a style-capable block: the text trimmed, and
 * ranges relative to that trimmed text. */
export function styledTextPayload({ text, styles }: StyledText): {
  correctedText: string;
  correctedStyles: StyleRun[];
} {
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
