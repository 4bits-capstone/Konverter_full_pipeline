const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const

function validDateParts(year: number, month: number, day: number): boolean {
  const candidate = new Date(Date.UTC(year, month - 1, day))
  return candidate.getUTCFullYear() === year
    && candidate.getUTCMonth() === month - 1
    && candidate.getUTCDate() === day
}

export function formatPublicationDate(value: string): string {
  const raw = value.trim().replace(/\.$/, '')
  if (!raw) return 'date not specified'
  const normalized = raw
    .replace(/^published\s+(?:on\s+)?/i, '')
    .replace(/(\d)(?:st|nd|rd|th)\b/gi, '$1')
    .trim()

  const iso = normalized.match(/^(\d{4})[-/](\d{2})[-/](\d{2})(?:[T\s].*)?$/)
  if (iso) {
    const [, yearValue, monthValue, dayValue] = iso
    const year = Number(yearValue)
    const month = Number(monthValue)
    const day = Number(dayValue)
    if (validDateParts(year, month, day)) return `${MONTHS[month - 1]} ${day}, ${year}`
  }

  const numericDayFirst = normalized.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?:[T\s].*)?$/)
  if (numericDayFirst) {
    const [, dayValue, monthValue, yearValue] = numericDayFirst
    const day = Number(dayValue)
    const month = Number(monthValue)
    const year = Number(yearValue)
    if (validDateParts(year, month, day)) return `${MONTHS[month - 1]} ${day}, ${year}`
  }

  const dayFirst = normalized.match(/^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/)
  if (dayFirst) {
    const [, dayValue, monthValue, yearValue] = dayFirst
    const month = MONTHS.findIndex((name) => name.toLowerCase().startsWith(monthValue.toLowerCase())) + 1
    const day = Number(dayValue)
    const year = Number(yearValue)
    if (month && validDateParts(year, month, day)) return `${MONTHS[month - 1]} ${day}, ${year}`
  }

  const monthFirst = normalized.match(/^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$/)
  if (monthFirst) {
    const [, monthValue, dayValue, yearValue] = monthFirst
    const month = MONTHS.findIndex((name) => name.toLowerCase().startsWith(monthValue.toLowerCase())) + 1
    const day = Number(dayValue)
    const year = Number(yearValue)
    if (month && validDateParts(year, month, day)) return `${MONTHS[month - 1]} ${day}, ${year}`
  }

  return normalized
}

export function publicationYear(value: string): string {
  const raw = value.trim().replace(/\.$/, '')
  if (!raw) return ''
  const normalized = raw
    .replace(/^published\s+(?:on\s+)?/i, '')
    .replace(/(\d)(?:st|nd|rd|th)\b/gi, '$1')
    .trim()
  const iso = normalized.match(/^(\d{4})[-/]/)
  if (iso) return iso[1]
  const yearMatch = normalized.match(/\b(19|20)\d{2}\b/)
  return yearMatch ? yearMatch[0] : ''
}

export function publicationDateLine(value: string): string {
  return `Published on ${formatPublicationDate(value)}.`
}
