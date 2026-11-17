import Bold from "@tiptap/extension-bold";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import Italic from "@tiptap/extension-italic";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Placeholder, UndoRedo } from "@tiptap/extensions";
import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useRef } from "react";
import {
  docToStyledText,
  sameStyledText,
  styledTextToDoc,
  type StyledText,
} from "../lib/styledText";

/**
 * The review pane's style-capable text field: a small rich-text editor that
 * shows italic and bold as they will appear, instead of `*markers*`.
 *
 * The document model stays deliberately tiny (paragraphs, hard breaks,
 * italic, bold) because the API only stores plain text plus ranges. Input
 * rules are off, so a literal `*` in a citation is never turned into a mark.
 */

interface StyledTextEditorProps {
  value: StyledText;
  editable: boolean;
  onChange: (value: StyledText) => void;
}

export function StyledTextEditor({
  value,
  editable,
  onChange,
}: StyledTextEditorProps) {
  // Keep the latest callback without recreating the editor on every render.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  // The last document we handed to (or received from) the editor, so the
  // sync effect can skip a full doc walk on every keystroke.
  const lastValueRef = useRef<StyledText>(value);

  const editor = useEditor({
    extensions: [
      Document,
      Paragraph,
      Text,
      Bold,
      Italic,
      HardBreak,
      UndoRedo,
      Placeholder.configure({ placeholder: "No text or image was extracted." }),
    ],
    content: styledTextToDoc(value),
    editable,
    // Typing `*` must stay a literal asterisk (legal citations are full of
    // them); formatting is applied with the toolbar or Ctrl+B / Ctrl+I.
    enableInputRules: false,
    enablePasteRules: false,
    // The I/B buttons reflect the cursor's marks, so re-render on selection.
    shouldRerenderOnTransaction: true,
    editorProps: {
      attributes: {
        role: "textbox",
        "aria-multiline": "true",
        "aria-label": "Extracted text",
        "aria-describedby": "extracted-text-help",
      },
    },
    onUpdate: ({ editor: current }) => {
      const next = docToStyledText(current.getJSON());
      lastValueRef.current = next;
      onChangeRef.current(next);
    },
  });

  // Controlled-ish sync: only replace the document when the incoming value
  // really differs, so typing never fights React (or moves the caret).
  useEffect(() => {
    if (!editor) return;
    if (sameStyledText(value, lastValueRef.current)) return;
    editor.commands.setContent(styledTextToDoc(value), { emitUpdate: false });
    lastValueRef.current = value;
  }, [editor, value]);

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(editable, false);
    editor.view.dom.setAttribute("aria-readonly", editable ? "false" : "true");
  }, [editor, editable]);

  if (!editor) return null;

  return (
    <div className="review-rich-text">
      {editable && (
        <div
          className="footnote-style-toolbar"
          role="toolbar"
          aria-label="Text style"
        >
          <button
            type="button"
            className="btn btn-outline btn-sm"
            aria-label="Italic"
            aria-pressed={editor.isActive("italic")}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => editor.chain().focus().toggleItalic().run()}
          >
            <em>I</em>
          </button>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            aria-label="Bold"
            aria-pressed={editor.isActive("bold")}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => editor.chain().focus().toggleBold().run()}
          >
            <strong>B</strong>
          </button>
          <small>
            Select text, then choose a style. Ctrl+B and Ctrl+I work too.
          </small>
        </div>
      )}
      <EditorContent
        editor={editor}
        className={`extract-box extract-input review-extracted-text review-rich-text-input${
          editable ? "" : " is-readonly"
        }`}
      />
    </div>
  );
}
