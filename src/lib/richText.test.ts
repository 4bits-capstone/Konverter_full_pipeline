import { describe, expect, it } from 'vitest'
import { readRich, renderRich, richPayload, richValue } from './richText'

const run = (start: number, end: number, italic = false, bold = false) => ({ start, end, italic, bold })

function read(html: string) {
  const root = document.createElement('div')
  root.innerHTML = html
  return readRich(root)
}

describe('richValue / richPayload', () => {
  it('trims the text and rebases the ranges onto it', () => {
    expect(richValue('  See Smith v Jones.\n', [run(6, 19, true)])).toEqual({
      text: 'See Smith v Jones.',
      styles: [run(4, 17, true)],
    })
  })

  it('drops ranges that fall entirely in trimmed whitespace', () => {
    expect(richValue('  hi', [run(0, 2, true)]).styles).toEqual([])
  })

  it('builds the API payload', () => {
    expect(richPayload({ text: ' a b ', styles: [run(1, 2, true)] })).toEqual({
      correctedText: 'a b',
      correctedStyles: [run(0, 1, true)],
    })
  })
})

describe('renderRich', () => {
  it('wraps styled runs in em/strong and leaves the rest as text', () => {
    const root = document.createElement('div')
    renderRich(root, { text: 'See Smith v Jones (1990).', styles: [run(4, 17, true), run(18, 24, false, true)] })
    expect(root.innerHTML).toBe('See <em>Smith v Jones</em> <strong>(1990)</strong>.')
  })

  it('nests both marks for a run that is italic and bold', () => {
    const root = document.createElement('div')
    renderRich(root, { text: 'both', styles: [run(0, 4, true, true)] })
    expect(root.innerHTML).toBe('<strong><em>both</em></strong>')
  })

  it('escapes markup-looking text instead of interpreting it', () => {
    const root = document.createElement('div')
    renderRich(root, { text: '<b>x</b> & *y*', styles: [] })
    expect(root.querySelector('b')).toBeNull()
    expect(root.textContent).toBe('<b>x</b> & *y*')
  })
})

describe('readRich', () => {
  it('reads <i>/<em> and <b>/<strong> the same way', () => {
    const expected = { text: 'a b c', styles: [run(0, 1, true), run(2, 3, false, true)] }
    expect(read('<i>a</i> <b>b</b> c')).toEqual(expected)
    expect(read('<em>a</em> <strong>b</strong> c')).toEqual(expected)
  })

  it('merges nested marks into one run carrying both', () => {
    expect(read('x <b><i>ab</i></b>')).toEqual({ text: 'x ab', styles: [run(2, 4, true, true)] })
  })

  it('merges adjacent runs with the same style', () => {
    expect(read('<b>a</b><strong>b</strong>').styles).toEqual([run(0, 2, false, true)])
  })

  it('understands browser-generated styled spans', () => {
    expect(read('<span style="font-weight: bold">a</span><span style="font-style: italic">b</span>')).toEqual({
      text: 'ab',
      styles: [run(0, 1, false, true), run(1, 2, true, false)],
    })
  })

  it('lets a normal-weight span cancel an enclosing bold', () => {
    expect(read('<b>a<span style="font-weight: normal">b</span></b>').styles).toEqual([run(0, 1, false, true)])
  })

  it('turns <br> and block elements into newlines', () => {
    expect(read('one<br>two').text).toBe('one\ntwo')
    expect(read('one<div>two</div><div>three</div>').text).toBe('one\ntwo\nthree')
    expect(read('one<div><br></div><div>three</div>').text).toBe('one\n\nthree')
  })

  it('keeps ranges aligned across line breaks', () => {
    expect(read('a<br><b>b</b>')).toEqual({ text: 'a\nb', styles: [run(2, 3, false, true)] })
  })
})

describe('render then read', () => {
  it.each([
    { text: 'See Smith v Jones (1990).', styles: [run(4, 17, true), run(18, 24, false, true)] },
    { text: 'plain only', styles: [] },
    { text: 'line one\n\nline *two*', styles: [run(14, 20, true, true)] },
    { text: 'a < b & c', styles: [run(0, 1, false, true)] },
  ])('round-trips %j', (value) => {
    const root = document.createElement('div')
    renderRich(root, value)
    expect(readRich(root)).toEqual(value)
  })
})
