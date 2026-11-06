import { h, nodes } from './dom'
import { count, same, show } from './format'
import { brand, section, table } from './parts'
import type { Review, ReviewAxis, ReviewCase, ReviewVariant } from './types'

const AXES: (string | [string, string])[] = [
  'Axis',
  ['Scale', 'Nominal values are compared with the baseline; ordinal and numeric values step by step.'],
  [
    'Role',
    'Causal: changing it changes the correct answer of some case. Invariant: the correct answer never depends on it.',
  ],
  ['Baseline', 'The value every other variant is compared with.'],
  'Values',
]

export function review(el: HTMLElement, scenario: Review) {
  const state = { case: 0 }
  const root = h('div', { class: 'ms' })
  el.replaceChildren(root)

  const draw = () => {
    const current = scenario.cases[state.case]
    root.replaceChildren(
      ...nodes(
        brand(),
        header(scenario),
        section(
          'Axes',
          'An axis is one thing the scenario varies. Its role says whether the correct answer should follow it.',
          table(AXES, scenario.axes.map(axis)),
        ),
        scenario.system &&
          section(
            'System prompt',
            'Sent as written with every variant.',
            h('pre', { class: 'ms-prompt' }, scenario.system),
          ),
        current &&
          section(
            'Variants',
            'Every variant of one case. Struck-through words leave the baseline prompt and highlighted words enter it. A highlighted answer differs from the baseline answer.',
            scenario.cases.length > 1 && picker(scenario.cases, state.case, choose),
            variants(current),
          ),
      ),
    )
  }

  const choose = (index: number) => {
    state.case = index
    draw()
  }

  draw()
}

function header(scenario: Review) {
  const variants = scenario.cases.reduce((total, item) => total + item.variants.length, 0)
  const facts: [string, string][] = [
    ['cases', count(scenario.cases.length)],
    ['variants', count(variants)],
    ['calls per target', count(variants * scenario.repetitions)],
  ]
  return h(
    'header',
    { class: 'ms-header' },
    h('h2', null, scenario.name, ' ', h('span', { class: 'ms-muted' }, `v${scenario.version}`)),
    scenario.description && h('p', null, scenario.description),
    h(
      'dl',
      { class: 'ms-stats' },
      facts.map(([term, value]) => h('div', null, h('dt', null, term), h('dd', null, value))),
    ),
    h(
      'p',
      { class: 'ms-intro' },
      'Every prompt this scenario asks, with its correct answer. Before anything runs, check that each variant changes only what its label names, and that each correct answer is right.',
    ),
  )
}

function axis(item: ReviewAxis) {
  return h(
    'tr',
    null,
    h('td', null, item.name),
    h('td', null, item.scale),
    h(
      'td',
      null,
      h('span', { class: item.role === 'causal' ? 'ms-badge ms-causal' : 'ms-badge' }, item.role),
    ),
    h('td', null, show(item.baseline)),
    h('td', { class: 'ms-wrap' }, item.values.map(show).join(item.scale === 'nominal' ? ', ' : ' < ')),
  )
}

function picker(cases: ReviewCase[], active: number, choose: (index: number) => void) {
  const select = h(
    'select',
    { class: 'ms-select', 'aria-label': 'Case' },
    cases.map((item, index) =>
      h('option', { value: String(index), selected: index === active }, `case ${item.case}`),
    ),
  )
  select.addEventListener('change', () => {
    choose(Number(select.value))
  })
  return select
}

function variants(item: ReviewCase) {
  return h(
    'div',
    { class: 'ms-variants' },
    item.variants.map((entry) => variant(entry, item.reference)),
  )
}

function variant(item: ReviewVariant, baseline: unknown) {
  const label = item.changed.map(([name, value]) => `${name}=${show(value)}`).join(', ')
  return h(
    'div',
    { class: 'ms-side' },
    h(
      'div',
      { class: 'ms-side-header' },
      h('span', null, label || 'baseline'),
      h(
        'span',
        { class: same(item.reference, baseline) ? 'ms-badge' : 'ms-badge ms-causal' },
        `correct: ${show(item.reference)}`,
      ),
    ),
    h(
      'pre',
      { class: 'ms-prompt' },
      item.parts.map(([text, kind]) =>
        kind === 'same' ? text : h(kind === 'added' ? 'ins' : 'del', null, text),
      ),
    ),
    item.system !== undefined &&
      h('details', null, h('summary', null, 'system prompt'), h('pre', null, item.system ?? 'none')),
  )
}
