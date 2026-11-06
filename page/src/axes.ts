import { color, intervals } from './chart'
import { h } from './dom'
import { interval, magnitude, number, shifted, show } from './format'
import { caption, info, muted, shift } from './parts'
import type { AxisScore, Inspect, Scorecard } from './types'

export function axes(cards: Scorecard[], inspect: Inspect) {
  return h(
    'div',
    { class: 'ms-grid' },
    cards[0]?.axes.map((score) => axis(score, cards, inspect)),
  )
}

function axis({ axis: name, scale, role }: AxisScore, cards: Scorecard[], inspect: Inspect) {
  const scores = cards.map((card) => card.axes.find((item) => item.axis === name))
  const values = [
    ...new Set(scores.flatMap((score) => score?.accuracy.map((point) => show(point.coordinate[name])) ?? [])),
  ]
  const rows = values.map((value) => {
    const points = scores.map((score) =>
      score?.accuracy.find((point) => show(point.coordinate[name]) === value),
    )
    return {
      label: value,
      value: cards.length === 1 ? number(points[0]?.estimate.value) : undefined,
      marks: points.flatMap((point, lane) =>
        point
          ? [
              {
                estimate: point.estimate,
                lane,
                color: color(lane),
                title: `${point.target} · ${name}=${value}: ${interval(point.estimate)}`,
                select: () => {
                  inspect({ kind: 'point', title: `${point.target} · ${name}=${value}`, point })
                },
              },
            ]
          : [],
      ),
    }
  })
  const shifts = scores.flatMap((score) => score?.shifts ?? [])
  return h(
    'article',
    { class: 'ms-card' },
    h(
      'header',
      { class: 'ms-card-header' },
      h('h4', null, name),
      h(
        'span',
        { class: 'ms-badges' },
        h('span', { class: 'ms-badge', title: SCALES[scale] }, scale),
        h('span', { class: `ms-badge ms-${role}` }, role),
        info(ROLES[role]),
      ),
    ),
    h('p', { class: 'ms-muted ms-purpose' }, PURPOSES[role]),
    caption(
      'Accuracy at each value',
      'Share of correct answers at each value of this axis, with every other axis at its first value. The line is the 95% interval. Click a dot to read the outputs.',
    ),
    intervals(rows, [0, 1], [0, 0.5, 1], cards.length),
    flips(name, scores, cards),
    caption(
      'Shifts beyond noise',
      "A shift is a step on this axis where answers change more than the model's own run-to-run noise. Orange: the axis should not matter, so the shift is a flaw. Excess: the change beyond noise. p: the chance of a change this large from noise alone, corrected for the number of steps tested. Click one to read the outputs.",
    ),
    shifts.length === 0 && muted('None'),
    shifts.map((candidate) => {
      const { start, end, target } = candidate.transition
      const step = `${show(start[name])} → ${show(end[name])}`
      const label = cards.length > 1 ? `${target} · ${step}` : step
      return shift(candidate, label, role === 'invariant', scale === 'numeric', () => {
        inspect({ kind: 'transition', title: `${target} · ${name}: ${step}`, candidate })
      })
    }),
  )
}

const ROLES: Record<AxisScore['role'], string> = {
  causal: 'Causal: changing this axis changes the correct answer, so answers should shift.',
  invariant: 'Invariant: changing this axis never changes the correct answer, so any shift is a flaw.',
}

const PURPOSES: Record<AxisScore['role'], string> = {
  causal: 'Should change the answer',
  invariant: 'Should not change the answer',
}

const SCALES: Record<AxisScore['scale'], string> = {
  nominal: 'Each value is compared with the baseline',
  ordinal: 'Each value is compared with the next, in order',
  numeric: 'Each number is compared with the next, and by the size of the step',
}

function flips(name: string, scores: (AxisScore | undefined)[], cards: Scorecard[]) {
  const reference = scores.find((score) => score?.threshold)?.threshold?.reference
  if (reference == null) return null
  const values = scores.flatMap(
    (score) => score?.accuracy.map((point) => Number(point.coordinate[name])) ?? [],
  )
  const domain: [number, number] = [Math.min(...values), Math.max(...values)]
  const found = scores.map((score) => {
    const offset = score?.threshold?.offset
    return offset ? shifted(offset, reference) : null
  })
  const single = cards.length === 1
  return [
    caption(
      'Where the answer flips',
      'The value at which the model switches its answer, beside the value at which the correct answer switches. Ideally they coincide. Width: how gradual the switch is.',
    ),
    intervals(
      [
        {
          label: 'answer',
          value: single ? magnitude(found[0]?.value) : undefined,
          marks: found.flatMap((estimate, lane) =>
            estimate
              ? [
                  {
                    estimate,
                    lane,
                    color: color(lane),
                    title: `${cards[lane]?.target ?? ''}: ${interval(estimate, magnitude)}`,
                  },
                ]
              : [],
          ),
        },
        {
          label: 'correct',
          value: single ? magnitude(reference) : undefined,
          marks: [
            {
              estimate: { value: reference, lower: null, upper: null },
              lane: 0,
              color: 'var(--ms-muted)',
              title: `The correct answer flips at ${magnitude(reference)}`,
            },
          ],
        },
      ],
      domain,
      ticks(domain, reference),
      cards.length,
    ),
    scores.map((score, lane) => {
      const width = score?.threshold?.width
      const label = single ? '' : `${cards[lane]?.target ?? ''}: `
      return muted(width ? `${label}width ${interval(width, magnitude)}` : `${label}no flip within the axis`)
    }),
  ]
}

function ticks([lower, upper]: [number, number], reference: number) {
  const room = (upper - lower) * 0.15
  return [
    ...(reference - lower > room ? [lower] : []),
    reference,
    ...(upper - reference > room ? [upper] : []),
  ]
}
