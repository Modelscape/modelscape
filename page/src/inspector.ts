import { histogram } from './chart'
import { h } from './dom'
import { coordinate, interval, number, probability, same, show } from './format'
import { muted } from './parts'
import type { Output, Selection } from './types'

const SHOWN = 5

const TERMS: Record<string, string> = {
  between: 'How often the answer differs between the two sides of this step',
  within: "How often the answer differs between repetitions of the same prompt: the model's own noise",
  excess: 'between minus within: the change beyond noise',
  p: 'The chance of a change this large from noise alone, corrected for the number of steps tested',
  observations: 'The outputs this number is computed from',
}

const UNAVAILABLE =
  'Pass the run to see what the model said: modelscape view report.json --store modelscape.db, or ReportPage(report, results).'

export function measurements(selection: Selection) {
  return selection.kind === 'transition' ? selection.candidate.transition.outputs : selection.point.outputs
}

export function inspector(
  selection: Selection,
  outputs: Output[] | null,
  expanded: boolean,
  expand: () => void,
  close: () => void,
) {
  return h(
    'div',
    { class: 'ms-inspector' },
    h(
      'header',
      { class: 'ms-inspector-header' },
      h(
        'div',
        null,
        h('h4', null, selection.title),
        h(
          'dl',
          { class: 'ms-stats' },
          statistics(selection).map(([term, value]) =>
            h('div', null, h('dt', { title: TERMS[term] ?? null }, term), h('dd', null, value)),
          ),
        ),
        selection.kind === 'transition' && muted(selection.candidate.rationale),
      ),
      h('button', { class: 'ms-close', title: 'Close', click: close }, '×'),
    ),
    distribution(selection),
    outputs == null
      ? muted(UNAVAILABLE)
      : outputs.length === 0
        ? muted('No stored outputs found for this number.')
        : evidence(selection, outputs, expanded, expand),
  )
}

function evidence(selection: Selection, outputs: Output[], expanded: boolean, expand: () => void) {
  const listed = cases(selection).filter(([name]) => outputs.some((item) => item.case === name))
  const shown = expanded ? listed : listed.slice(0, SHOWN)
  return [
    shown.map(([name, summary]) => {
      const found = outputs.filter((item) => item.case === name)
      return h(
        'section',
        { class: 'ms-case' },
        h(
          'header',
          { class: 'ms-case-header' },
          h('h4', null, name),
          h('span', { class: 'ms-muted' }, summary),
        ),
        h(
          'div',
          { class: 'ms-sides' },
          sides(found, selection).map((group) => side(group, label(group, outputs))),
        ),
      )
    }),
    shown.length < listed.length &&
      h('button', { class: 'ms-more', click: expand }, `Show all ${String(listed.length)} cases`),
  ]
}

function distribution(selection: Selection) {
  const [label, chart] =
    selection.kind === 'transition'
      ? [
          'Excess change per case',
          histogram(
            selection.candidate.transition.per_case.flatMap((item) =>
              item.excess == null ? [] : [item.excess],
            ),
            [-1, 1],
            [-1, 0, 1],
            0.1,
            (center, count) => `excess ${center.toFixed(1)}: ${String(count)} cases`,
          ),
        ]
      : [
          'Accuracy per case',
          histogram(
            selection.point.per_case.map((item) => item.value),
            [0, 1],
            [0, 0.5, 1],
            0.1,
            (center, count) => `accuracy ${center.toFixed(1)}: ${String(count)} cases`,
          ),
        ]
  return h('figure', { class: 'ms-figure' }, h('p', { class: 'ms-label' }, label), chart)
}

function statistics(selection: Selection): [string, string][] {
  if (selection.kind === 'point') {
    return [
      ['accuracy', interval(selection.point.estimate)],
      ['observations', String(selection.point.observations)],
    ]
  }
  const { between, within, excess, observations } = selection.candidate.transition
  return [
    ['between', interval(between)],
    ['within', interval(within)],
    ['excess', interval(excess)],
    ['p', probability(selection.candidate.adjusted_p_value)],
    ['observations', String(observations)],
  ]
}

function cases(selection: Selection): [string, string][] {
  return selection.kind === 'transition'
    ? selection.candidate.transition.per_case
        .slice()
        .sort((a, b) => (b.excess ?? -Infinity) - (a.excess ?? -Infinity))
        .map((item) => [item.case, `excess ${number(item.excess)} · within ${number(item.within)}`])
    : selection.point.per_case
        .slice()
        .sort((a, b) => a.value - b.value)
        .map((item) => [item.case, `accuracy ${number(item.value)}`])
}

function sides(outputs: Output[], selection: Selection) {
  const groups = new Map<string, [Output, ...Output[]]>()
  for (const item of outputs) {
    const key = `${item.target} ${coordinate(item.coordinate)}`
    const group = groups.get(key)
    if (group) group.push(item)
    else groups.set(key, [item])
  }
  const leading = (item: Output) =>
    selection.kind === 'transition' &&
    item.target === selection.candidate.transition.target &&
    Object.entries(selection.candidate.transition.start).every(([axis, value]) =>
      same(item.coordinate[axis], value),
    )
  return [...groups.values()].sort((a, b) => Number(leading(b[0])) - Number(leading(a[0])))
}

function label([item]: [Output, ...Output[]], all: Output[]) {
  const axes = Object.keys(item.coordinate).filter((axis) =>
    all.some((other) => !same(other.coordinate[axis], item.coordinate[axis])),
  )
  const target = new Set(all.map((other) => other.target)).size > 1 ? [item.target] : []
  return (
    [...target, coordinate(item.coordinate, axes)].filter(Boolean).join(' · ') || coordinate(item.coordinate)
  )
}

function side(outputs: [Output, ...Output[]], title: string) {
  const { prompt, reference } = outputs[0]
  const messages = [
    ...(prompt.system ? [{ role: 'system', content: prompt.system }] : []),
    ...prompt.messages,
  ]
  return h(
    'div',
    { class: 'ms-side' },
    h(
      'div',
      { class: 'ms-side-header' },
      h('span', { class: 'ms-truncate ms-strong' }, title),
      h('span', { class: 'ms-muted' }, `expects ${show(reference)}`),
    ),
    h(
      'details',
      null,
      h('summary', null, 'Prompt'),
      messages.map((message) => h('div', null, muted(message.role), h('pre', null, message.content))),
    ),
    outputs.map((output) =>
      h(
        'div',
        { class: 'ms-output' },
        h('span', { class: 'ms-muted' }, `#${String(output.repetition)}`),
        output.score != null &&
          h('span', { class: output.score >= 1 ? 'ms-good' : 'ms-bad' }, output.score >= 1 ? '✓' : '✗'),
        h('pre', { class: output.error ? 'ms-bad' : null }, output.error ?? output.text),
      ),
    ),
  )
}
