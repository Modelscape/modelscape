import { type Child, h } from './dom'
import { interval, magnitude, shifted, show } from './format'
import type { AxisScore, Inspect, Scorecard } from './types'

const READABLE = 0.95
const STEPS = 3

export function findings(cards: Scorecard[], inspect: Inspect) {
  return h(
    'div',
    { class: 'ms-findings' },
    cards.map((card) => finding(card, inspect)),
  )
}

function finding(card: Scorecard, inspect: Inspect) {
  const flawed = card.axes.filter((axis) => axis.role === 'invariant' && axis.shifts.length > 0)
  const ignored = card.axes.filter((axis) => axis.role === 'causal' && axis.shifts.length === 0)
  const followed = card.axes.filter((axis) => axis.role === 'causal' && axis.shifts.length > 0)
  const misplaced = followed.filter(({ threshold }) => {
    const offset = threshold?.offset
    return offset?.lower != null && offset.upper != null && (offset.lower > 0 || offset.upper < 0)
  })
  const correct = followed.filter((axis) => !misplaced.includes(axis))
  const unreadable = card.answered != null && card.answered < READABLE
  return h(
    'article',
    { class: 'ms-finding' },
    h('h4', null, card.target),
    h(
      'ul',
      null,
      flawed.map((axis) =>
        item(
          false,
          'Answers shift with ',
          h('code', null, axis.axis),
          ', which should not matter: ',
          steps(card, axis, inspect),
        ),
      ),
      ignored.map((axis) =>
        item(false, 'Answers do not follow ', h('code', null, axis.axis), ', which should change them.'),
      ),
      misplaced.map(({ axis, threshold }) =>
        threshold?.offset
          ? item(
              false,
              'Answers flip on ',
              h('code', null, axis),
              ` at ${interval(shifted(threshold.offset, threshold.reference), magnitude)}, but should flip at ${magnitude(threshold.reference)}.`,
            )
          : null,
      ),
      unreadable &&
        item(
          false,
          `Only ${String(Math.round((card.answered ?? 0) * 100))}% of outputs had a readable answer; the rest count as wrong.`,
        ),
      flawed.length === 0 && item(true, 'No shifts on axes that should not matter.'),
      correct.length > 0 &&
        item(
          true,
          'Answers follow ',
          correct.map((axis, index) => [index > 0 && ', ', h('code', null, axis.axis)]),
          ', as they should.',
        ),
    ),
  )
}

function item(good: boolean, ...children: Child[]) {
  return h(
    'li',
    { class: good ? 'ms-good-item' : 'ms-bad-item' },
    h('span', { class: good ? 'ms-good' : 'ms-bad', 'aria-label': good ? 'good' : 'flaw' }, good ? '✓' : '✗'),
    h('span', null, ...children),
  )
}

function steps({ target }: Scorecard, { axis, shifts }: AxisScore, inspect: Inspect) {
  const shown = shifts.slice(0, STEPS).map((candidate, index) => {
    const { start, end } = candidate.transition
    const step = `${show(start[axis])} → ${show(end[axis])}`
    return [
      index > 0 && ', ',
      h(
        'button',
        {
          class: 'ms-step',
          title: 'Read the outputs behind this shift',
          click: () => {
            inspect({ kind: 'transition', title: `${target} · ${axis}: ${step}`, candidate })
          },
        },
        step,
      ),
    ]
  })
  const more = shifts.length - STEPS
  return [shown, more > 0 && `, and ${String(more)} more`, '.']
}
