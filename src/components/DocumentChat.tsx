import {
  MessageCircle,
  Mic,
  MicOff,
  Radio,
  Send,
  Square,
  Volume2,
  X,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { runtimeConfig } from "../config/runtime";
import { supabase } from "../lib/supabaseClient";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const MAX_HISTORY_MESSAGES = 20;
const MAX_MESSAGE_CHARS = 4000;
const SPEECH_LANG = "en-AU";

// Generic enough to make sense for any reviewed report, so they don't need
// per-document topic extraction to be useful as a starting point.
const STARTER_PROMPTS = [
  "Summarize this document",
  "What are the key recommendations?",
  "Who published this and when?",
];

type ChatBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "bullet-list"; items: string[] }
  | { kind: "numbered-list"; items: string[] };

// A deliberately small, dependency-free markdown reader: the chat backend
// sometimes replies with **bold**, bullet, or numbered-list syntax, and
// showing that literally (asterisks and all) reads as broken. This covers
// the handful of patterns a document-QA assistant actually produces —
// nothing more — rather than pulling in a full markdown library.
export function parseChatBlocks(content: string): ChatBlock[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ChatBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }
    if (/^\s*[-*+]\s+/.test(lines[index])) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].match(/^\s*[-*+]\s+(.*)/);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push({ kind: "bullet-list", items });
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(lines[index])) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].match(/^\s*\d+[.)]\s+(.*)/);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push({ kind: "numbered-list", items });
      continue;
    }
    const paragraphLines: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index])
    ) {
      paragraphLines.push(lines[index].replace(/^#{1,6}\s+/, ""));
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraphLines.join(" ") });
  }
  return blocks;
}

function renderInline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter((part) => part !== "")
    .map((part, index) => {
      const bold = part.match(/^\*\*([^*]+)\*\*$/);
      return bold ? (
        <strong key={index}>{bold[1]}</strong>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      );
    });
}

function ChatMessageContent({ text }: { text: string }) {
  const blocks = useMemo(() => parseChatBlocks(text), [text]);
  return (
    <>
      {blocks.map((block, index) => {
        if (block.kind === "bullet-list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }
        if (block.kind === "numbered-list") {
          return (
            <ol key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInline(item)}</li>
              ))}
            </ol>
          );
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </>
  );
}

function stripMarkdown(value: string): string {
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(\*|_)(.*?)\1/g, "$2")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/^>\s?/gm, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s+/g, " ")
    .trim();
}

async function authHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.clone().json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Response wasn't JSON (e.g. a streamed reply that failed after the
    // first chunk) — fall back to the generic message below.
  }
  return fallback;
}

export function DocumentChat({ documentId }: { documentId: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [convoMode, setConvoMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Streaming updates the visible transcript on every chunk, which would
  // otherwise spam a screen reader with dozens of "polite" announcements
  // per reply. The visible log stays silent (aria-live="off") while a
  // message streams in; this separate, visually hidden region announces
  // once, after the full reply is ready.
  const [announcement, setAnnouncement] = useState("");
  const [speechSupported] = useState(
    () =>
      typeof window !== "undefined" &&
      Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
  );

  const convoModeRef = useRef(convoMode);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  // speak()'s onended callback fires long after the render that created it,
  // so it reads the latest startListening through a ref (same reasoning as
  // convoModeRef) rather than closing over a possibly-stale callback.
  const startListeningRef = useRef<() => void>(() => {});

  useEffect(() => {
    convoModeRef.current = convoMode;
  }, [convoMode]);

  // A new document means a new conversation; also stop anything from the
  // previous document mid-flight (voice, audio, an in-progress reply).
  useEffect(() => {
    setMessages([]);
    setInput("");
    setError(null);
    setAnnouncement("");
    setConvoMode(false);
    recognitionRef.current?.stop();
    audioRef.current?.pause();
    abortRef.current?.abort();
  }, [documentId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(
    () => () => {
      recognitionRef.current?.stop();
      audioRef.current?.pause();
      abortRef.current?.abort();
    },
    [],
  );

  const speak = useCallback(async (text: string) => {
    const spoken = stripMarkdown(text);
    if (!spoken) return;
    setIsSpeaking(true);
    try {
      const headers = await authHeaders();
      const response = await fetch(`${runtimeConfig.apiBaseUrl}/tts`, {
        method: "POST",
        headers,
        body: JSON.stringify({ text: spoken }),
      });
      if (!response.ok) {
        setError(await readErrorDetail(response, "Voice reply isn't available right now."));
        setIsSpeaking(false);
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
        if (convoModeRef.current) startListeningRef.current();
      };
      audio.onerror = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
      };
      await audio.play();
    } catch {
      setIsSpeaking(false);
      setError("Voice reply isn't available right now.");
    }
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      setError(null);
      setInput("");
      const history = messages.slice(-MAX_HISTORY_MESSAGES);
      setMessages((current) => [
        ...current,
        { role: "user", content: trimmed },
        { role: "assistant", content: "" },
      ]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      let assistantText = "";
      const appendToReply = (chunk: string) => {
        assistantText += chunk;
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === "assistant") {
            next[next.length - 1] = { ...last, content: assistantText };
          }
          return next;
        });
      };

      try {
        const headers = await authHeaders();
        const response = await fetch(
          `${runtimeConfig.apiBaseUrl}/documents/${encodeURIComponent(documentId)}/chat`,
          {
            method: "POST",
            headers,
            signal: controller.signal,
            body: JSON.stringify({ message: trimmed, history }),
          },
        );

        if (!response.ok) {
          const detail = await readErrorDetail(
            response,
            "The assistant couldn't answer that. Please try again.",
          );
          setMessages((current) => current.slice(0, -1));
          setError(detail);
          return;
        }

        if (!response.body) {
          appendToReply(await response.text());
        } else {
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            appendToReply(decoder.decode(value, { stream: true }));
          }
        }

        if (assistantText.trim()) {
          setAnnouncement(`Assistant replied: ${stripMarkdown(assistantText)}`);
        }
        if (convoModeRef.current && assistantText.trim()) {
          void speak(assistantText);
        }
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setMessages((current) => current.slice(0, -1));
        setError("The connection was interrupted. Please try again.");
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [documentId, isStreaming, messages, speak],
  );

  const startListening = useCallback(() => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Voice input isn't supported in this browser.");
      return;
    }
    if (recognitionRef.current || isStreaming || isSpeaking) return;

    const recognition = new Recognition();
    recognition.lang = SPEECH_LANG;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      if (transcript.trim()) void sendMessage(transcript);
    };
    recognition.onerror = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };
    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };
    recognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }, [isSpeaking, isStreaming, sendMessage]);

  useEffect(() => {
    startListeningRef.current = startListening;
  }, [startListening]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const toggleConvoMode = useCallback(() => {
    setConvoMode((current) => {
      const next = !current;
      if (next) startListening();
      else stopListening();
      return next;
    });
  }, [startListening, stopListening]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void sendMessage(input);
  };

  const cancelStreaming = () => {
    abortRef.current?.abort();
  };

  if (!isOpen) {
    return (
      <div className="chat-widget">
        <button
          type="button"
          className="chat-widget-fab"
          onClick={() => setIsOpen(true)}
          aria-label="Ask about this document"
        >
          <MessageCircle aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className="chat-widget">
      <div className="chatcard chat-widget-panel">
        <div className="chatcard-head">
          <div>
            <h4>Ask about this document</h4>
            <p className="chatcard-hint">
              Answers use this document&rsquo;s reviewed content and
              structured export as context.
            </p>
          </div>
          <button
            type="button"
            className="chat-widget-close"
            onClick={() => setIsOpen(false)}
            aria-label="Close chat"
          >
            <X aria-hidden="true" />
          </button>
        </div>

        <div className="chat-messages" role="log" aria-live="off">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <p>Ask a question about this document to get started.</p>
            <div className="chat-starter-prompts">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="chat-starter-prompt"
                  onClick={() => void sendMessage(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <div
              key={index}
              className={`chat-message chat-message-${message.role}`}
            >
              <span className="chat-message-role">
                {message.role === "user" ? "You" : "Assistant"}
              </span>
              {message.content ? (
                message.role === "assistant" ? (
                  <ChatMessageContent text={message.content} />
                ) : (
                  <p>{message.content}</p>
                )
              ) : (
                <span
                  className="chat-typing"
                  role="status"
                  aria-label="Assistant is typing"
                >
                  <span />
                  <span />
                  <span />
                </span>
              )}
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>

      {error && (
        <p className="chat-error" role="alert">
          {error}
        </p>
      )}

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="document-chat-input">
          Ask a question about this document
        </label>
        <textarea
          id="document-chat-input"
          className="input"
          rows={2}
          maxLength={MAX_MESSAGE_CHARS}
          placeholder="Ask a question about this document…"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void sendMessage(input);
            }
          }}
        />
        {input.length > MAX_MESSAGE_CHARS * 0.9 && (
          <span className="chat-char-count">
            {input.length} / {MAX_MESSAGE_CHARS}
          </span>
        )}
        <div className="chat-input-actions">
          {speechSupported && (
            <button
              type="button"
              className={`btn btn-outline btn-sm icon-button ${isListening ? "chat-mic-active" : ""}`}
              onClick={isListening ? stopListening : startListening}
              disabled={isStreaming || isSpeaking}
              aria-pressed={isListening}
              aria-label={isListening ? "Stop voice input" : "Start voice input"}
              title={isListening ? "Stop voice input" : "Start voice input"}
            >
              {isListening ? <MicOff aria-hidden="true" /> : <Mic aria-hidden="true" />}
            </button>
          )}
          {speechSupported && (
            <button
              type="button"
              className={`btn btn-outline btn-sm icon-button ${convoMode ? "chat-convo-active" : ""}`}
              onClick={toggleConvoMode}
              aria-pressed={convoMode}
              aria-label={
                convoMode
                  ? "Turn off hands-free conversation mode"
                  : "Turn on hands-free conversation mode"
              }
              title={
                convoMode
                  ? "Turn off hands-free conversation mode"
                  : "Turn on hands-free conversation mode"
              }
            >
              <Radio aria-hidden="true" />
            </button>
          )}
          {isStreaming ? (
            <button
              type="button"
              className="btn btn-outline btn-sm icon-button"
              onClick={cancelStreaming}
              aria-label="Stop generating"
              title="Stop generating"
            >
              <Square aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              className="btn btn-primary btn-sm icon-button"
              disabled={!input.trim()}
              aria-label="Send"
              title="Send"
            >
              <Send aria-hidden="true" />
            </button>
          )}
        </div>
      </form>

        <div className="chat-status" aria-live="polite">
          {isListening && <span>Listening…</span>}
          {isSpeaking && (
            <span>
              <Volume2 aria-hidden="true" /> Speaking…
            </span>
          )}
          {convoMode && !isListening && !isSpeaking && !isStreaming && (
            <span>Conversation mode is on.</span>
          )}
        </div>
      </div>
    </div>
  );
}
