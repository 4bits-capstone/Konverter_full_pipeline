import { describe, expect, it } from "vitest";
import {
  docToStyledText,
  sameStyledText,
  styledTextPayload,
  styledTextToDoc,
} from "./styledText";
import type { StyleRun } from "../types/konverter";

const run = (
  start: number,
  end: number,
  italic = false,
  bold = false,
): StyleRun => ({ start, end, italic, bold });

describe("styledText", () => {
  it("round-trips plain text", () => {
    const value = { text: "See Smith v Jones.", styles: [] };
    expect(docToStyledText(styledTextToDoc(value))).toEqual(value);
  });

  it("round-trips paragraphs and single newlines", () => {
    const text =
      "First paragraph.\nSecond line.\n\nSecond paragraph.\n\n\nAfter a blank line.";
    expect(docToStyledText(styledTextToDoc({ text, styles: [] }))).toEqual({
      text,
      styles: [],
    });
  });

  it("puts ranges on the matching words", () => {
    const text = "See Smith v Jones (1990).";
    const doc = styledTextToDoc({
      text,
      styles: [run(4, 17, true, false)],
    });

    expect(doc.content?.[0]?.content).toEqual([
      { type: "text", text: "See " },
      { type: "text", text: "Smith v Jones", marks: [{ type: "italic" }] },
      { type: "text", text: " (1990)." },
    ]);
    expect(docToStyledText(doc)).toEqual({
      text,
      styles: [run(4, 17, true, false)],
    });
  });

  it("splits overlapping ranges into per-character runs", () => {
    const text = "abcdef";
    const doc = styledTextToDoc({
      text,
      styles: [run(0, 4, true, false), run(2, 6, false, true)],
    });

    expect(docToStyledText(doc)).toEqual({
      text,
      styles: [
        run(0, 2, true, false),
        run(2, 4, true, true),
        run(4, 6, false, true),
      ],
    });
  });

  it("clamps ranges that fall outside the text", () => {
    expect(
      docToStyledText(
        styledTextToDoc({ text: "abc", styles: [run(-5, 99, true, false)] }),
      ),
    ).toEqual({ text: "abc", styles: [run(0, 3, true, false)] });
  });

  it("splits a style at a hard break", () => {
    const text = "ab\ncd";
    expect(
      docToStyledText(
        styledTextToDoc({ text, styles: [run(0, 5, true, false)] }),
      ),
    ).toEqual({
      text,
      styles: [run(0, 2, true, false), run(3, 5, true, false)],
    });
  });

  it("compares values without depending on object identity", () => {
    expect(
      sameStyledText(
        { text: "abc", styles: [run(0, 2, true, false)] },
        { text: "abc", styles: [run(0, 2, true, false)] },
      ),
    ).toBe(true);
    expect(
      sameStyledText(
        { text: "abc", styles: [run(0, 2, true, false)] },
        { text: "abc", styles: [run(0, 2, false, true)] },
      ),
    ).toBe(false);
    expect(
      sameStyledText(
        { text: "abc", styles: [] },
        { text: "abd", styles: [] },
      ),
    ).toBe(false);
  });

  it("trims the text and shifts ranges for the API payload", () => {
    expect(
      styledTextPayload({ text: "  abc  ", styles: [run(2, 5, true, false)] }),
    ).toEqual({
      correctedText: "abc",
      correctedStyles: [run(0, 3, true, false)],
    });
  });

  it("drops ranges that fall entirely outside the trimmed text", () => {
    expect(
      styledTextPayload({ text: "  abc  ", styles: [run(0, 2, true, false)] }),
    ).toEqual({ correctedText: "abc", correctedStyles: [] });
  });
});
