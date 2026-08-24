export {}

// Web Speech API types aren't part of TypeScript's default DOM lib. This
// declares only the surface DocumentChat uses for voice input.
declare global {
  interface SpeechRecognitionEventResultItem {
    transcript: string
  }

  interface SpeechRecognitionEventResult {
    0: SpeechRecognitionEventResultItem
    length: number
  }

  interface SpeechRecognitionEvent extends Event {
    results: ArrayLike<SpeechRecognitionEventResult>
  }

  interface SpeechRecognitionErrorEvent extends Event {
    error: string
  }

  interface SpeechRecognition extends EventTarget {
    lang: string
    continuous: boolean
    interimResults: boolean
    start(): void
    stop(): void
    abort(): void
    onresult: ((event: SpeechRecognitionEvent) => void) | null
    onerror: ((event: SpeechRecognitionErrorEvent) => void) | null
    onend: (() => void) | null
  }

  interface Window {
    SpeechRecognition?: new () => SpeechRecognition
    webkitSpeechRecognition?: new () => SpeechRecognition
  }
}
