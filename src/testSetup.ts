import '@testing-library/jest-dom/vitest'

// jsdom doesn't implement the Blob URL registry at all — real browsers
// always do, so this is purely a test-environment gap, not a product
// concern. A tiny deterministic stand-in (a counter-keyed "blob:" string)
// is enough for anything asserting on distinct object URLs.
if (typeof URL.createObjectURL !== 'function') {
  let counter = 0
  URL.createObjectURL = () => `blob:mock-${++counter}`
  URL.revokeObjectURL = () => {}
}
