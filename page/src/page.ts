import { axes } from './axes'
import { legend } from './chart'
import { divergence } from './divergence'
import { findings } from './findings'
import { h, nodes } from './dom'
import { inspector, measurements } from './inspector'
import { resolve } from './outputs'
import { brand, info, section } from './parts'
import { provenance } from './provenance'
import { scorecards } from './scorecards'
import type { Data, Report, Selection } from './types'

interface State {
  card: number
  selection: Selection | null
  expanded: boolean
}

function header(report: Report) {
  return h(
    'header',
    { class: 'ms-header' },
    h('h2', null, report.scenario.name, ' ', h('span', { class: 'ms-muted' }, `v${report.scenario.version}`)),
    h(
      'p',
      { class: 'ms-intro' },
      "Every variant of the task was asked several times, so each model's own run-to-run noise is known. ",
      'A shift is a change in answers beyond that noise. On an axis that should not matter, a shift is a flaw. ',
      'Click any dot or shift to read the outputs behind it, and hover ',
      info('Like this one. Each explains the part of the page it sits on.'),
      ' for help.',
    ),
  )
}

export function render(el: HTMLElement, { report, outputs }: Data) {
  const state: State = { card: 0, selection: null, expanded: false }
  const root = h('div', { class: 'ms' })
  el.replaceChildren(root)

  const draw = () => {
    const card = report.scorecards[Math.min(state.card, report.scorecards.length - 1)]
    const group = report.scorecards.filter((item) => item.group === card?.group)
    const { selection } = state
    root.replaceChildren(
      ...nodes(
        brand(),
        header(report),
        card &&
          section(
            card.group === 'all' ? 'Findings' : `Findings · ${card.group}`,
            'What the numbers below say, in words. Click a step to read the outputs behind it.',
            findings(group, inspect),
          ),
        section(
          'Scorecards',
          'One row per model: its headline numbers. A good model has high accuracy and answered, and zero spurious and missed change.',
          scorecards(report.scorecards, card?.group, select),
        ),
        card &&
          section(
            `Axes · ${card.group}`,
            'An axis is one thing the scenario varies, such as a name or an amount. Each card shows how the answers respond to it.',
            group.length > 1 && legend(group.map((item) => item.target)),
            axes(group, inspect),
          ),
        selection &&
          inspector(
            selection,
            outputs && resolve(outputs, measurements(selection)),
            state.expanded,
            expand,
            close,
          ),
        report.divergences.length > 0 &&
          section(
            'Divergence',
            'Where a model answers differently from the first model, beyond the noise of both.',
            divergence(report.divergences, inspect),
          ),
        section(
          'Provenance',
          'What produced these numbers: versions, model settings, failed calls, tokens, and cost.',
          provenance(report.provenance, report.experiment),
        ),
      ),
    )
  }

  const select = (index: number) => {
    state.card = index
    draw()
  }

  const inspect = (selection: Selection) => {
    state.selection = selection
    state.expanded = false
    draw()
    root.querySelector('.ms-inspector')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  const expand = () => {
    state.expanded = true
    draw()
  }

  const close = () => {
    state.selection = null
    draw()
  }

  draw()
}
