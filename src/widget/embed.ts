/**
 * Standalone, dependency-free embeddable chat widget for exported Konverter
 * HTML documents (e.g. pasted into a WordPress staging page). No React, no
 * build-time dependency on the main app — this file is compiled on its own
 * (see package.json's build:widget script) into a single IIFE that reads
 * its config from `window.__KONVERTER_CHAT__` and mounts itself on load.
 *
 * It talks to the unauthenticated `/api/public/documents/{id}/chat`
 * endpoint (see backend/app/main.py), not the reviewer-only `/chat`
 * endpoint the in-app widget uses, since page visitors here have no
 * Konverter/Supabase login.
 */

interface KonverterChatConfig {
  documentId: string;
  apiBase: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// SpeechRecognition/webkitSpeechRecognition are already declared globally on
// Window by ../types/speech.d.ts (shared with the in-app DocumentChat
// widget) — redeclaring them here with a different shape would conflict
// with that ambient declaration project-wide, so this only adds the two
// properties unique to this file.
declare global {
  interface Window {
    __KONVERTER_CHAT__?: KonverterChatConfig;
    __KONVERTER_CHAT_WIDGET_MOUNTED__?: boolean;
  }
}

const MAX_MESSAGE_CHARS = 4000;
const STARTER_PROMPTS = [
  "Summarize this document",
  "What are the key recommendations?",
  "Who published this and when?",
];

type ChatBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "bullet-list"; items: string[] }
  | { kind: "numbered-list"; items: string[] };

function parseChatBlocks(content: string): ChatBlock[] {
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

function stripMarkdownForAnnouncement(value: string): string {
  return value
    .replace(/(\*\*|__)(.*?)\1/g, "$2")
    .replace(/(\*|_)(.*?)\1/g, "$2")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function appendInline(parent: HTMLElement, text: string): void {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter((part) => part !== "");
  for (const part of parts) {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) {
      const strong = document.createElement("strong");
      strong.textContent = bold[1];
      parent.appendChild(strong);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  }
}

function renderMessageContent(container: HTMLElement, text: string): void {
  container.innerHTML = "";
  for (const block of parseChatBlocks(text)) {
    if (block.kind === "bullet-list" || block.kind === "numbered-list") {
      const list = document.createElement(
        block.kind === "bullet-list" ? "ul" : "ol",
      );
      for (const item of block.items) {
        const li = document.createElement("li");
        appendInline(li, item);
        list.appendChild(li);
      }
      container.appendChild(list);
      continue;
    }
    const p = document.createElement("p");
    appendInline(p, block.text);
    container.appendChild(p);
  }
}

const WIDGET_CSS = `
.kcw-widget{position:fixed;right:24px;bottom:24px;z-index:2147483000;font-family:Arial,"Helvetica Neue",sans-serif}
.kcw-widget *{box-sizing:border-box}
.kcw-fab{display:flex;align-items:center;justify-content:center;width:56px;height:56px;border:none;border-radius:50%;background:#005493;color:#fff;box-shadow:0 8px 24px rgba(0,49,88,.32);cursor:pointer}
.kcw-fab[hidden]{display:none}
.kcw-fab:hover,.kcw-fab:focus-visible{background:#003f73}
.kcw-fab svg{width:24px;height:24px}
.kcw-panel{display:flex;flex-direction:column;width:min(380px,calc(100vw - 48px));height:min(560px,calc(100vh - 140px));background:#fff;border:1px solid #d5d5d5;border-radius:8px;box-shadow:0 16px 44px rgba(0,32,64,.22);padding:16px;gap:10px;color:#1c1c1c}
.kcw-panel[hidden]{display:none}
.kcw-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.kcw-head h4{font-size:13px;font-weight:600;margin:0}
.kcw-hint{font-size:12px;color:#6b6b6b;margin:4px 0 0}
.kcw-close{display:flex;align-items:center;justify-content:center;width:28px;height:28px;flex-shrink:0;border:none;border-radius:6px;background:transparent;color:#6b6b6b;cursor:pointer}
.kcw-close:hover,.kcw-close:focus-visible{background:#f3f7fa;color:#1c1c1c}
.kcw-close svg{width:18px;height:18px}
.kcw-messages{display:flex;flex-direction:column;gap:8px;flex:1 1 auto;min-height:0;overflow-y:auto;padding-right:2px}
.kcw-empty{display:flex;flex-direction:column;gap:10px}
.kcw-empty p{font-size:12.5px;color:#6b6b6b;margin:0}
.kcw-starters{display:flex;flex-direction:column;gap:6px}
.kcw-starter{text-align:left;font-size:12.5px;font-weight:500;color:#003f73;background:#f3f7fa;border:1px solid #b8b8b8;border-radius:8px;padding:8px 12px;cursor:pointer}
.kcw-starter:hover,.kcw-starter:focus-visible{background:#f6f6f6;border-color:#005493}
.kcw-message{border-radius:8px;padding:8px 10px;font-size:13px;line-height:1.5;max-width:92%}
.kcw-message p{margin:8px 0 0;white-space:pre-wrap}
.kcw-message>*:first-child{margin-top:4px}
.kcw-message ul,.kcw-message ol{margin:8px 0 0;padding-left:20px}
.kcw-message li+li{margin-top:2px}
.kcw-role{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:#6b6b6b}
.kcw-message-user{background:#f3f7fb;align-self:flex-end}
.kcw-message-assistant{background:#f6f6f6}
.kcw-typing{display:inline-flex;align-items:center;gap:3px;margin-top:4px;height:14px}
.kcw-typing span{width:5px;height:5px;border-radius:50%;background:#6b6b6b;animation:kcw-bounce 1.1s ease-in-out infinite}
.kcw-typing span:nth-child(2){animation-delay:.15s}
.kcw-typing span:nth-child(3){animation-delay:.3s}
@keyframes kcw-bounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-3px);opacity:1}}
.kcw-error{font-size:12px;color:#8a1f1f;background:#fbeaea;border:1px solid #e3b7b7;border-radius:6px;padding:6px 9px;margin:0}
.kcw-input-row{display:flex;flex-direction:column;gap:8px}
.kcw-input-row textarea{resize:vertical;font:13px/1.4 Arial,"Helvetica Neue",sans-serif;padding:8px 10px;border:1px solid #b8b8b8;border-radius:6px;min-height:44px}
.kcw-char-count{align-self:flex-end;font-size:11px;color:#6b6b6b;margin-top:-4px}
.kcw-actions{display:flex;justify-content:flex-end;gap:6px}
.kcw-icon-btn{display:flex;align-items:center;justify-content:center;min-width:34px;height:34px;padding:7px;border:1px solid #b8b8b8;border-radius:6px;background:#fff;color:#1c1c1c;cursor:pointer}
.kcw-icon-btn[hidden]{display:none}
.kcw-icon-btn svg{width:16px;height:16px}
.kcw-icon-btn:disabled{opacity:.45;cursor:not-allowed}
.kcw-icon-btn.kcw-active{color:#003f73;background:#f3f7fa;border-color:#005493}
.kcw-icon-btn-primary{background:#005493;border-color:#003f73;color:#fff}
.kcw-icon-btn-primary:disabled{opacity:.45}
.kcw-status{font-size:11.5px;color:#6b6b6b;min-height:14px}
.kcw-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media (max-width:520px){.kcw-widget{right:12px;bottom:12px}.kcw-panel{width:calc(100vw - 24px);height:min(520px,calc(100vh - 110px))}}
`;

const ICONS = {
  message:
    '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
  micOff:
    '<path d="M2 2l20 20M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V5a3 3 0 0 0-5.94-.6M19 10v2a7 7 0 0 1-.11 1.23M12 19v3M8 23h8"/>',
  send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
  stop: '<rect width="14" height="14" x="5" y="5" rx="2"/>',
};

function svg(path: string): string {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function mountKonverterChatWidget(config: KonverterChatConfig): void {
  const apiBase = config.apiBase.replace(/\/+$/, "");
  const documentId = config.documentId;

  const style = document.createElement("style");
  style.textContent = WIDGET_CSS;
  document.head.appendChild(style);

  const root = document.createElement("div");
  root.className = "kcw-widget";
  document.body.appendChild(root);

  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "kcw-fab";
  fab.setAttribute("aria-label", "Ask about this document");
  fab.innerHTML = svg(ICONS.message);

  const panel = document.createElement("div");
  panel.className = "kcw-panel";
  panel.hidden = true;
  panel.innerHTML = `
    <div class="kcw-head">
      <div>
        <h4>Ask about this document</h4>
        <p class="kcw-hint">Answers use this document&rsquo;s reviewed content and structured export as context.</p>
      </div>
      <button type="button" class="kcw-close" aria-label="Close chat">${svg(ICONS.close)}</button>
    </div>
    <div class="kcw-messages" role="log" aria-live="off"></div>
    <div class="kcw-sr-only" role="status" aria-live="polite"></div>
    <form class="kcw-input-row">
      <label class="kcw-sr-only" for="kcw-input">Ask a question about this document</label>
      <textarea id="kcw-input" rows="2" maxlength="${MAX_MESSAGE_CHARS}" placeholder="Ask a question about this document…"></textarea>
      <span class="kcw-char-count" hidden></span>
      <div class="kcw-actions">
        <button type="button" class="kcw-icon-btn kcw-mic-btn" aria-label="Start voice input" title="Start voice input" hidden>${svg(ICONS.mic)}</button>
        <button type="submit" class="kcw-icon-btn kcw-icon-btn-primary kcw-send-btn" aria-label="Send" title="Send" disabled>${svg(ICONS.send)}</button>
      </div>
    </form>
    <div class="kcw-status" aria-live="polite"></div>
  `;

  root.appendChild(fab);
  root.appendChild(panel);

  const messagesEl = panel.querySelector<HTMLElement>(".kcw-messages")!;
  const announceEl = panel.querySelector<HTMLElement>(".kcw-sr-only")!;
  const form = panel.querySelector<HTMLFormElement>(".kcw-input-row")!;
  const textarea = panel.querySelector<HTMLTextAreaElement>("#kcw-input")!;
  const charCountEl = panel.querySelector<HTMLElement>(".kcw-char-count")!;
  const sendBtn = panel.querySelector<HTMLButtonElement>(".kcw-send-btn")!;
  const micBtn = panel.querySelector<HTMLButtonElement>(".kcw-mic-btn")!;
  const closeBtn = panel.querySelector<HTMLButtonElement>(".kcw-close")!;
  const statusEl = panel.querySelector<HTMLElement>(".kcw-status")!;

  let messages: ChatMessage[] = [];
  let isStreaming = false;
  let isListening = false;
  let recognition: SpeechRecognition | null = null;

  const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognitionCtor) micBtn.hidden = false;

  function renderMessages(): void {
    messagesEl.innerHTML = "";
    if (messages.length === 0) {
      const empty = document.createElement("div");
      empty.className = "kcw-empty";
      const p = document.createElement("p");
      p.textContent = "Ask a question about this document to get started.";
      empty.appendChild(p);
      const starters = document.createElement("div");
      starters.className = "kcw-starters";
      for (const prompt of STARTER_PROMPTS) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "kcw-starter";
        btn.textContent = prompt;
        btn.addEventListener("click", () => void sendMessage(prompt));
        starters.appendChild(btn);
      }
      empty.appendChild(starters);
      messagesEl.appendChild(empty);
      return;
    }
    for (const message of messages) {
      const bubble = document.createElement("div");
      bubble.className = `kcw-message kcw-message-${message.role}`;
      const role = document.createElement("span");
      role.className = "kcw-role";
      role.textContent = message.role === "user" ? "You" : "Assistant";
      bubble.appendChild(role);
      if (message.content) {
        if (message.role === "assistant") {
          const content = document.createElement("div");
          renderMessageContent(content, message.content);
          bubble.appendChild(content);
        } else {
          const p = document.createElement("p");
          p.textContent = message.content;
          bubble.appendChild(p);
        }
      } else {
        const typing = document.createElement("span");
        typing.className = "kcw-typing";
        typing.setAttribute("role", "status");
        typing.setAttribute("aria-label", "Assistant is typing");
        typing.innerHTML = "<span></span><span></span><span></span>";
        bubble.appendChild(typing);
      }
      messagesEl.appendChild(bubble);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setError(message: string | null): void {
    let errorEl = panel.querySelector<HTMLElement>(".kcw-error");
    if (!message) {
      errorEl?.remove();
      return;
    }
    if (!errorEl) {
      errorEl = document.createElement("p");
      errorEl.className = "kcw-error";
      errorEl.setAttribute("role", "alert");
      messagesEl.insertAdjacentElement("afterend", errorEl);
    }
    errorEl.textContent = message;
  }

  async function sendMessage(rawText: string): Promise<void> {
    const trimmed = rawText.trim();
    if (!trimmed || isStreaming) return;

    setError(null);
    textarea.value = "";
    charCountEl.hidden = true;
    const history = messages.slice(-20).map((m) => ({ role: m.role, content: m.content }));
    messages = [...messages, { role: "user", content: trimmed }, { role: "assistant", content: "" }];
    isStreaming = true;
    sendBtn.disabled = true;
    renderMessages();

    let assistantText = "";
    const appendToReply = (chunk: string) => {
      assistantText += chunk;
      messages = [...messages];
      messages[messages.length - 1] = { role: "assistant", content: assistantText };
      renderMessages();
    };

    try {
      const response = await fetch(
        `${apiBase}/public/documents/${encodeURIComponent(documentId)}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, history }),
        },
      );

      if (!response.ok) {
        let detail = "The assistant couldn't answer that. Please try again.";
        try {
          const body = await response.clone().json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // non-JSON error body; keep the generic message
        }
        messages = messages.slice(0, -1);
        setError(detail);
        renderMessages();
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
        announceEl.textContent = `Assistant replied: ${stripMarkdownForAnnouncement(assistantText)}`;
      }
    } catch {
      messages = messages.slice(0, -1);
      setError("The connection was interrupted. Please try again.");
      renderMessages();
    } finally {
      isStreaming = false;
      sendBtn.disabled = !textarea.value.trim();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage(textarea.value);
  });

  textarea.addEventListener("input", () => {
    sendBtn.disabled = !textarea.value.trim();
    const remaining = textarea.value.length;
    if (remaining > MAX_MESSAGE_CHARS * 0.9) {
      charCountEl.hidden = false;
      charCountEl.textContent = `${remaining} / ${MAX_MESSAGE_CHARS}`;
    } else {
      charCountEl.hidden = true;
    }
  });

  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage(textarea.value);
    }
  });

  function stopListening(): void {
    recognition?.stop();
  }

  function startListening(): void {
    if (!SpeechRecognitionCtor || recognition || isStreaming) return;
    recognition = new SpeechRecognitionCtor();
    recognition.lang = "en-AU";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results?.[0]?.[0]?.transcript ?? "";
      if (transcript.trim()) void sendMessage(transcript);
    };
    recognition.onerror = () => {
      isListening = false;
      recognition = null;
      updateMicButton();
    };
    recognition.onend = () => {
      isListening = false;
      recognition = null;
      updateMicButton();
    };
    isListening = true;
    updateMicButton();
    recognition.start();
  }

  function updateMicButton(): void {
    micBtn.classList.toggle("kcw-active", isListening);
    micBtn.innerHTML = svg(isListening ? ICONS.micOff : ICONS.mic);
    micBtn.setAttribute(
      "aria-label",
      isListening ? "Stop voice input" : "Start voice input",
    );
    statusEl.textContent = isListening ? "Listening…" : "";
  }

  micBtn.addEventListener("click", () => {
    if (isListening) stopListening();
    else startListening();
  });

  closeBtn.addEventListener("click", () => {
    panel.hidden = true;
    fab.hidden = false;
  });

  fab.addEventListener("click", () => {
    fab.hidden = true;
    panel.hidden = false;
    textarea.focus();
  });

  renderMessages();
}

(function init() {
  if (window.__KONVERTER_CHAT_WIDGET_MOUNTED__) return;
  const config = window.__KONVERTER_CHAT__;
  if (!config || !config.documentId || !config.apiBase) return;
  window.__KONVERTER_CHAT_WIDGET_MOUNTED__ = true;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountKonverterChatWidget(config));
  } else {
    mountKonverterChatWidget(config);
  }
})();

export {};
