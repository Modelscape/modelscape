import { h, svg } from './dom'
import type { Estimate } from './types'

const LANE = 12
const SERIES = 8

export interface Mark {
  estimate: Estimate
  lane: number
  color: string
  title: string
  select?: (() => void) | undefined
}

export interface Row {
  label: string
  marks: Mark[]
  value?: string | undefined
}

type Scale = (value: number) => string

export const color = (series: number) =>
  series < SERIES ? `var(--ms-series-${String(series + 1)})` : 'var(--ms-muted)'

function scale([lower, upper]: [number, number]): Scale {
  return (value) => `${String(((Math.min(upper, Math.max(lower, value)) - lower) / (upper - lower)) * 100)}%`
}

function grid(ticks: number[], at: Scale, height: number) {
  return ticks.map((tick) =>
    svg('line', {
      class: tick === 0 && ticks[0] !== 0 ? 'ms-gridline ms-zero' : 'ms-gridline',
      x1: at(tick),
      x2: at(tick),
      y1: 0,
      y2: height,
    }),
  )
}

function axis(ticks: number[], at: Scale) {
  return svg(
    'svg',
    { class: 'ms-track ms-axis', height: 16 },
    ticks.map((tick, index) =>
      svg(
        'text',
        {
          x: at(tick),
          y: 12,
          'text-anchor': index === 0 ? 'start' : index === ticks.length - 1 ? 'end' : 'middle',
        },
        Math.abs(tick) >= 1000 ? tick.toLocaleString('en-US') : String(Number(tick.toFixed(2))),
      ),
    ),
  )
}

function mark({ estimate, lane, color: fill, title, select }: Mark, at: Scale) {
  const y = LANE * (lane + 0.5) + 4
  const { value, lower, upper } = estimate
  const group = svg(
    'g',
    { class: select ? 'ms-mark ms-selectable' : 'ms-mark', style: `color: ${fill}` },
    svg('title', {}, title),
    svg('rect', { x: 0, y: y - LANE / 2, width: '100%', height: LANE }),
    lower != null && upper != null && svg('line', { x1: at(lower), x2: at(upper), y1: y, y2: y }),
    svg('circle', { cx: at(value), cy: y, r: 4 }),
  )
  if (select) group.addEventListener('click', select)
  return group
}

export function intervals(
  rows: Row[],
  domain: [number, number],
  ticks: number[],
  lanes: number,
  wide = false,
) {
  const at = scale(domain)
  const height = lanes * LANE + 8
  return h(
    'div',
    { class: wide ? 'ms-plot ms-wide' : 'ms-plot' },
    rows.map((row) =>
      h(
        'div',
        { class: 'ms-plot-row' },
        h('span', { class: 'ms-truncate', title: row.label }, row.label),
        svg(
          'svg',
          { class: 'ms-track', height },
          grid(ticks, at, height),
          row.marks.map((item) => mark(item, at)),
        ),
        h('span', { class: 'ms-number' }, row.value ?? ''),
      ),
    ),
    h('div', { class: 'ms-plot-row' }, h('span', null), axis(ticks, at), h('span', null)),
  )
}

export function histogram(
  values: number[],
  [first, last]: [number, number],
  ticks: number[],
  step: number,
  describe: (center: number, count: number) => string,
) {
  const domain: [number, number] = [first - step / 2, last + step / 2]
  const at = scale(domain)
  const counts = Array.from({ length: Math.round((last - first) / step) + 1 }, () => 0)
  for (const value of values) {
    const index = Math.min(counts.length - 1, Math.max(0, Math.round((value - first) / step)))
    counts[index] = (counts[index] ?? 0) + 1
  }
  const tallest = Math.max(1, ...counts)
  const height = 56
  return h(
    'div',
    { class: 'ms-histogram' },
    svg(
      'svg',
      { class: 'ms-track', height },
      counts.map((count, index) => {
        const lower = domain[0] + index * step
        const size = (count / tallest) * (height - 4)
        return svg(
          'g',
          { class: 'ms-bin' },
          svg('title', {}, describe(first + index * step, count)),
          svg('rect', { class: 'ms-bin-hit', x: at(lower), y: 0, width: at(domain[0] + step), height }),
          count > 0 &&
            svg('rect', {
              x: at(lower + step * 0.1),
              y: height - size,
              width: at(domain[0] + step * 0.8),
              height: size,
              rx: 1.5,
            }),
        )
      }),
      svg('line', { class: 'ms-gridline ms-zero', x1: 0, x2: '100%', y1: height, y2: height }),
    ),
    axis(ticks, at),
  )
}

export function legend(names: string[]) {
  return h(
    'div',
    { class: 'ms-legend' },
    names.map((name, index) =>
      h('span', null, h('span', { class: 'ms-swatch', style: `background: ${color(index)}` }), name),
    ),
  )
}
