import { h } from './dom'
import { count, moment, show } from './format'
import { table } from './parts'
import type { Provenance, TargetProvenance } from './types'

const COLUMNS = ['Target', 'Served', 'Observations', 'Failed', 'Input tokens', 'Output tokens', 'Cost']

export function provenance(record: Provenance, experiment: string) {
  const facts = [
    ['Experiment', experiment.slice(0, 12)],
    ['modelscape', record.modelscape],
    ['Python', record.python],
    ['Platform', record.platform],
    ['Report made', moment(record.created_at)],
    ['First observation', moment(record.first_observation)],
    ['Last observation', moment(record.last_observation)],
  ]
  return [
    h(
      'dl',
      { class: 'ms-facts' },
      facts.map(([term, value]) => h('div', null, h('dt', null, term), h('dd', null, value))),
    ),
    table(COLUMNS, record.targets.map(target)),
  ]
}

function target(item: TargetProvenance) {
  return h(
    'tr',
    null,
    h(
      'td',
      null,
      h('div', null, item.identity.name),
      h('div', { class: 'ms-muted ms-wrap' }, settings(item)),
    ),
    h('td', null, item.models.join(', ') || '–'),
    h('td', null, count(item.observations)),
    h('td', null, count(item.failed)),
    h('td', null, count(item.input_tokens)),
    h('td', null, count(item.output_tokens)),
    h('td', null, item.cost == null ? '–' : item.cost.toFixed(2)),
  )
}

function settings(item: TargetProvenance) {
  return Object.entries(item.identity.parameters)
    .filter(([, value]) => value != null && !(typeof value === 'object' && Object.keys(value).length === 0))
    .map(([key, value]) => `${key}=${show(value)}`)
    .join(' · ')
}
