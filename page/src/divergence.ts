import { intervals } from './chart'
import { h } from './dom'
import { coordinate, interval, number, probability, same, show } from './format'
import { caption, muted } from './parts'
import type { Divergence, Inspect } from './types'

const STEPS = [0.1, 0.2, 0.25, 0.5, 1]

export function divergence(divergences: Divergence[], inspect: Inspect) {
  return divergences.map(({ first, second, contrasts, candidates }) => {
    const axes = Object.keys(contrasts[0]?.end ?? {}).filter((axis) =>
      contrasts.some((item) => !same(item.end[axis], contrasts[0]?.end[axis])),
    )
    const reach = Math.max(
      0,
      ...contrasts.flatMap(({ excess }) =>
        excess ? [excess.value, excess.lower ?? 0, excess.upper ?? 0].map(Math.abs) : [],
      ),
    )
    const bound = STEPS.find((step) => step >= reach) ?? 1
    const rows = contrasts.flatMap((transition) => {
      const { excess, end } = transition
      if (!excess) return []
      const label = axes.map((axis) => show(end[axis])).join(' · ') || coordinate(end)
      const candidate = candidates.find((item) => coordinate(item.transition.end) === coordinate(end))
      return [
        {
          label,
          value: number(excess.value),
          marks: [
            {
              estimate: excess,
              lane: 0,
              color: candidate ? 'var(--ms-warn-mark)' : 'var(--ms-muted)',
              title: `${coordinate(end)}: excess ${interval(excess)}${candidate ? ` · p ${probability(candidate.adjusted_p_value)}` : ''}`,
              select:
                candidate &&
                (() => {
                  inspect({
                    kind: 'transition',
                    title: `${second} vs ${first} · ${coordinate(end)}`,
                    candidate,
                  })
                }),
            },
          ],
        },
      ]
    })
    return h(
      'article',
      { class: 'ms-card' },
      h(
        'h4',
        { class: 'ms-plain' },
        h('code', null, second),
        ' differs from ',
        h('code', null, first),
        ` beyond noise in ${String(candidates.length)} of ${String(contrasts.length)} comparisons`,
      ),
      rows.length === 0
        ? muted('No coordinates were compared.')
        : [
            caption(
              `Difference beyond the noise of both models, by ${axes.join(' · ') || 'coordinate'}`,
              'How much more the two models differ than their own noise explains, at each point. Orange: a difference beyond noise; click it to read the outputs. Near 0: they agree.',
            ),
            intervals(rows, [-bound, bound], [-bound, 0, bound], 1, true),
          ],
    )
  })
}
