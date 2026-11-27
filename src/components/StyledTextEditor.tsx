import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ClipboardEvent, KeyboardEvent } from "react";
import { readRich, renderRich, type RichValue } from "../lib/richText";

interface StyledTextEditorProps {
  /** What the editor starts with. Only read on mount and when `resetKey`
   * changes -- while editing, the DOM is the source of truth. */
  value: RichValue;
  resetKey: string;
  onChange: (value: RichValue) => void;
  ariaLabel: string;
  ariaDescribedBy?: string;
  /** Headings and captions: no line breaks. */
  singleLine?: boolean;
}

type Mark = "italic" | "bold";

function markIsOn(mark: Mark): boolean {
  try {
    return document.queryCommandState(mark);
  } catch {
    return false;
  }
}

/** Collapse line breaks the way a single-line field would. */
const flatten = (value: string) => value.replace(/\s*\n+\s*/g, " ");

/**
 * Italic/bold shown as real formatting while the reviewer types. A plain
 * contenteditable: only bold and italic, newlines as plain "\n", and paste
 * as plain text, so nothing but those two marks can ever enter the text.
 */
export function StyledTextEditor({
  value,
  resetKey,
  onChange,
  ariaLabel,
  ariaDescribedBy,
  singleLine = false,
}: StyledTextEditorProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState<Record<Mark, boolean>>({
    italic: false,
    bold: false,
  });

  useLayoutEffect(() => {
    if (rootRef.current) renderRich(rootRef.current, value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  // Keep the toolbar's pressed state in step with the caret/selection.
  useEffect(() => {
    const sync = () => {
      const root = rootRef.current;
      const anchor = window.getSelection()?.anchorNode;
      if (!root || !anchor || !root.contains(anchor)) return;
      setActive({ italic: markIsOn("italic"), bold: markIsOn("bold") });
    };
    document.addEventListener("selectionchange", sync);
    return () => document.removeEventListener("selectionchange", sync);
  }, []);

  const emit = () => {
    if (rootRef.current) onChange(readRich(rootRef.current));
  };

  const toggle = (mark: Mark) => {
    rootRef.current?.focus();
    document.execCommand("styleWithCSS", false, "false");
    document.execCommand(mark);
    setActive((current) => ({ ...current, [mark]: markIsOn(mark) }));
    emit();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter") return;
    // Browsers differ on what Enter inserts (<div>, <br>, <p>); a plain
    // newline character keeps the text model identical everywhere.
    event.preventDefault();
    if (!singleLine) document.execCommand("insertText", false, "\n");
  };

  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault();
    const pasted = event.clipboardData.getData("text/plain");
    document.execCommand("insertText", false, singleLine ? flatten(pasted) : pasted);
  };

  return (
    <>
      <div
        className="footnote-style-toolbar"
        role="toolbar"
        aria-label="Text style"
      >
        <button
          type="button"
          className="btn btn-outline btn-sm"
          aria-label="Italic"
          aria-pressed={active.italic}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => toggle("italic")}
        >
          <em>I</em>
        </button>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          aria-label="Bold"
          aria-pressed={active.bold}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => toggle("bold")}
        >
          <strong>B</strong>
        </button>
        <small>Select text, then choose a style. Ctrl/⌘+B and Ctrl/⌘+I work too.</small>
      </div>
      <div
        ref={rootRef}
        className="extract-box extract-input review-extracted-text styled-text-editor"
        role="textbox"
        aria-multiline={!singleLine}
        aria-label={ariaLabel}
        aria-describedby={ariaDescribedBy}
        contentEditable
        suppressContentEditableWarning
        spellCheck
        onInput={emit}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
      />
    </>
  );
}
