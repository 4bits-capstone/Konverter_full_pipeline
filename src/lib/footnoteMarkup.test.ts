import { describe, expect, it } from "vitest";
import { footnotePayload, fromMarkup, toggleStyle, toMarkup } from "./footnoteMarkup";

const run = (start: number, end: number, italic = false, bold = false) => ({
  start,
  end,
  italic,
  bold,
});

describe("footnote markup", () => {
  it("writes detected styles as inline markers", () => {
    expect(toMarkup("See Smith v Jones (1990).", [run(4, 17, true)])).toBe(
      "See *Smith v Jones* (1990).",
    );
    expect(toMarkup("Ibid 5.", [run(0, 4, false, true)])).toBe("**Ibid** 5.");
    expect(toMarkup("Ibid 5.", [run(0, 4, true, true)])).toBe("***Ibid*** 5.");
  });

  it("reads markers back into text and ranges", () => {
    expect(fromMarkup("See *Smith v Jones* (1990).")).toEqual({
      text: "See Smith v Jones (1990).",
      styles: [run(4, 17, true)],
    });
    expect(fromMarkup("**Ibid** and ***both***")).toEqual({
      text: "Ibid and both",
      styles: [run(0, 4, false, true), run(9, 13, true, true)],
    });
  });

  it("round-trips text and styles, including literal asterisks and backslashes", () => {
    const text = "Note * and \\ then Smith v Jones.";
    const styles = [run(18, 31, true), run(0, 4, false, true)].sort(
      (a, b) => a.start - b.start,
    );
    const back = fromMarkup(toMarkup(text, styles));
    expect(back.text).toBe(text);
    expect(back.styles).toEqual(styles);
  });

  it("keeps an unpaired marker as literal text", () => {
    expect(fromMarkup("5 * 3 = 15")).toEqual({ text: "5 * 3 = 15", styles: [] });
    expect(fromMarkup("*open and never closed")).toEqual({
      text: "*open and never closed",
      styles: [],
    });
  });

  it("handles an italic run directly followed by a bold one", () => {
    expect(fromMarkup("*a***b**")).toEqual({
      text: "ab",
      styles: [run(0, 1, true), run(1, 2, false, true)],
    });
  });

  it("returns plain text and no styles when there are no markers", () => {
    expect(fromMarkup("Plain footnote.")).toEqual({
      text: "Plain footnote.",
      styles: [],
    });
    expect(toMarkup("Plain footnote.")).toBe("Plain footnote.");
  });

  it("trims the payload and keeps ranges relative to the trimmed text", () => {
    expect(footnotePayload("  *Ibid* 5.  ")).toEqual({
      correctedText: "Ibid 5.",
      correctedStyles: [run(0, 4, true)],
    });
    expect(footnotePayload("Plain.").correctedStyles).toEqual([]);
  });
});

describe("toggleStyle", () => {
  it("italicises a selection", () => {
    const markup = "See Smith v Jones (1990).";
    const result = toggleStyle(markup, 4, 17, "italic");
    expect(result.markup).toBe("See *Smith v Jones* (1990).");
    expect(result.markup.slice(result.selectionStart, result.selectionEnd)).toBe(
      "Smith v Jones",
    );
  });

  it("removes the style when the whole selection already has it", () => {
    const result = toggleStyle("See *Smith v Jones* (1990).", 5, 18, "italic");
    expect(result.markup).toBe("See Smith v Jones (1990).");
  });

  it("applies the style when only part of the selection has it", () => {
    const result = toggleStyle("*ab*cd", 1, 6, "italic");
    expect(fromMarkup(result.markup).styles).toEqual([run(0, 4, true)]);
  });

  it("combines italic and bold on the same words", () => {
    const result = toggleStyle("*Ibid* 5.", 0, 6, "bold");
    expect(fromMarkup(result.markup).styles).toEqual([run(0, 4, true, true)]);
  });

  it("does not mispair markers when the selection spans them", () => {
    const markup = "a *b* c";
    const result = toggleStyle(markup, 0, markup.length, "bold");
    const parsed = fromMarkup(result.markup);
    expect(parsed.text).toBe("a b c");
    expect(parsed.styles).toEqual([
      run(0, 2, false, true),
      run(2, 3, true, true),
      run(3, 5, false, true),
    ]);
  });

  it("keeps escaped asterisks as text and maps the selection around them", () => {
    const markup = "5 \\* 3 and word";
    const word = markup.indexOf("word");
    const result = toggleStyle(markup, word, markup.length, "bold");
    expect(fromMarkup(result.markup).text).toBe(fromMarkup(markup).text);
    expect(result.markup.endsWith("**word**")).toBe(true);
  });

  it("leaves the markup alone when nothing is selected", () => {
    expect(toggleStyle("abc", 1, 1, "italic").markup).toBe("abc");
  });
});

