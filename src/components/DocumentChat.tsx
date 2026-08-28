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
const CHAT_PANEL_EXIT_MS = 230;

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
  const [animationPhase, setAnimationPhase] = useState<
    "idle" | "opening" | "closing"
  >("idle");
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
  const audioUrlRef = useRef<string | null>(null);
  const speechAbortRef = useRef<AbortController | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<HTMLDivElement | null>(null);
  const fabRef = useRef<HTMLButtonElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  // speak()'s onended callback fires long after the render that created it,
  // so it reads the latest startListening through a ref (same reasoning as
  // convoModeRef) rather than closing over a possibly-stale callback.
  const startListeningRef = useRef<() => void>(() => {});

  const completeClose = useCallback(() => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsOpen(false);
    setAnimationPhase("idle");
    window.setTimeout(() => fabRef.current?.focus(), 0);
  }, []);

  const openChat = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setAnimationPhase("opening");
    setIsOpen(true);
  };

  const closeChat = () => {
    if (animationPhase === "closing") return;
    const reduceMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduceMotion) {
      completeClose();
      return;
    }
    setAnimationPhase("closing");
    closeTimerRef.current = window.setTimeout(
      completeClose,
      CHAT_PANEL_EXIT_MS,
    );
  };

  // The only way to cut off an in-progress voice reply: pause it directly
  // rather than waiting for 'ended'. Clearing the handlers first stops a
  // stray onended from re-triggering conversation mode's listen-again loop.
  const stopSpeaking = useCallback(() => {
    speechAbortRef.current?.abort();
    speechAbortRef.current = null;
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    audioRef.current = null;
    setIsSpeaking(false);
  }, []);

  useEffect(() => {
    convoModeRef.current = convoMode;
  }, [convoMode]);

  useEffect(() => {
    const content = document.getElementById("main-content");
    const header = document.querySelector<HTMLElement>(".converter-header");
    const documentBar = document.querySelector<HTMLElement>(".docbar");

    const updateSafeTop = () => {
      const contentTop = content?.getBoundingClientRect().top ?? 0;
      widgetRef.current?.style.setProperty(
        "--chat-safe-top",
        `${Math.max(16, Math.ceil(contentTop + 16))}px`,
      );
    };

    updateSafeTop();
    window.addEventListener("resize", updateSafeTop);

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(updateSafeTop);
    if (content) resizeObserver?.observe(content);
    if (header) resizeObserver?.observe(header);
    if (documentBar) resizeObserver?.observe(documentBar);

    return () => {
      window.removeEventListener("resize", updateSafeTop);
      resizeObserver?.disconnect();
    };
  }, [isOpen]);

  // A new document means a new conversation; also stop anything from the
  // previous document mid-flight (voice, audio, an in-progress reply).
  useEffect(() => {
    setMessages([]);
    setInput("");
    setError(null);
    setAnnouncement("");
    setConvoMode(false);
    recognitionRef.current?.stop();
    stopSpeaking();
    abortRef.current?.abort();
  }, [documentId, stopSpeaking]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(
    () => () => {
      recognitionRef.current?.stop();
      stopSpeaking();
      abortRef.current?.abort();
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
      }
    },
    [stopSpeaking],
  );

  const speak = useCallback(async (text: string) => {
    const spoken = stripMarkdown(text);
    if (!spoken) return;
    stopSpeaking();
    const controller = new AbortController();
    speechAbortRef.current = controller;
    setIsSpeaking(true);
    try {
      const headers = await authHeaders();
      if (controller.signal.aborted) return;
      const response = await fetch(`${runtimeConfig.apiBaseUrl}/tts`, {
        method: "POST",
        headers,
        signal: controller.signal,
        body: JSON.stringify({ text: spoken }),
      });
      if (controller.signal.aborted) return;
      if (!response.ok) {
        setError(await readErrorDetail(response, "Voice reply isn't available right now."));
        setIsSpeaking(false);
        return;
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
        audioUrlRef.current = null;
        if (convoModeRef.current) startListeningRef.current();
      };
      audio.onerror = () => {
        setIsSpeaking(false);
        URL.revokeObjectURL(url);
        audioUrlRef.current = null;
      };
      await audio.play();
    } catch {
      if (controller.signal.aborted) return;
      stopSpeaking();
      setError("Voice reply isn't available right now.");
    }
  }, [stopSpeaking]);

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
      if (next) {
        startListening();
      } else {
        // Turning conversation mode off should stop it *now*, including a
        // reply that's mid-playback — not just stop listening for the next
        // turn and let the current one keep talking until it ends on its own.
        stopListening();
        stopSpeaking();
      }
      return next;
    });
  }, [startListening, stopListening, stopSpeaking]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void sendMessage(input);
  };

  const cancelStreaming = () => {
    abortRef.current?.abort();
    stopSpeaking();
  };

  if (!isOpen) {
    return (
      <div className="chat-widget" ref={widgetRef}>
        <button
          ref={fabRef}
          type="button"
          className="chat-widget-fab"
          onClick={openChat}
          aria-label="Ask about this document"
        >
          <MessageCircle aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className="chat-widget" ref={widgetRef}>
      <div
        className={`chatcard chat-widget-panel is-${animationPhase === "idle" ? "open" : animationPhase}`}
        onAnimationEnd={(event) => {
          if (event.currentTarget !== event.target) return;
          if (animationPhase === "closing") completeClose();
          else if (animationPhase === "opening") setAnimationPhase("idle");
        }}
      >
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
            onClick={closeChat}
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
          {isStreaming || isSpeaking ? (
            <button
              type="button"
              className="btn btn-outline btn-sm icon-button"
              onClick={cancelStreaming}
              aria-label="Stop response"
              title="Stop response"
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
