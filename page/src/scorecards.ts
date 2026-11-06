import { h } from './dom'
import { interval, number } from './format'
import { table } from './parts'
import type { Scorecard } from './types'

const COLUMNS: (string | [string, string])[] = [
  'Target',
  ['Group', 'The cases these numbers cover. "all" covers every case.'],
  ['Cases', 'The number of cases. Every case is varied along every axis.'],
  [
    'Accuracy',
    'Share of correct answers at the baseline, where every axis has its first value. In brackets: the 95% interval. Ideal: 1.',
  ],
  [
    'Answered',
    'Share of outputs from which an answer could be read. An unreadable answer counts as wrong. Ideal: 1.',
  ],
  [
    'Spurious change',
    'How much answers change, beyond noise, where the correct answer stays the same. The model reacts to something that should not matter. Ideal: 0.',
  ],
  [
    'Missed change',
    'Share of answers that stay the same where the correct answer changes. The model ignores something that should matter. Ideal: 0.',
  ],
  [
    'Invariant shifts',
    'Steps on axes that should not matter where answers change beyond noise. Each is a flaw. Ideal: 0.',
  ],
]

export function scorecards(cards: Scorecard[], active: string | undefined, select: (index: number) => void) {
  const grouped = new Set(cards.map((card) => card.group)).size > 1
  return table(
    COLUMNS,
    cards.map((card, index) =>
      h(
        'tr',
        {
          class: grouped ? (card.group === active ? 'ms-active' : 'ms-clickable') : null,
          click: () => {
            select(index)
          },
        },
        h('td', null, card.target),
        h('td', null, card.group),
        h('td', null, card.cases.length),
        h('td', null, interval(card.accuracy)),
        h('td', null, number(card.answered)),
        h('td', null, number(card.spurious_change)),
        h('td', null, number(card.missed_change)),
        h('td', { class: flaws(card) > 0 ? 'ms-bad' : null }, flaws(card)),
      ),
    ),
  )
}

const flaws = (card: Scorecard) =>
  card.axes.reduce((total, axis) => total + (axis.role === 'invariant' ? axis.shifts.length : 0), 0)
