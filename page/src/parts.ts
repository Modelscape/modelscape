import { type Child, h } from './dom'
import { interval, precise, probability, rate } from './format'
import { logo } from './logo'
import type { Candidate } from './types'

const REPOSITORY = 'https://github.com/Modelscape/modelscape'

export function brand() {
  return h(
    'a',
    { class: 'ms-brand', href: REPOSITORY, target: '_blank', rel: 'noopener' },
    logo(),
    'modelscape',
  )
}

export function section(title: string, help: string, ...children: Child[]) {
  return h('section', { class: 'ms-section' }, h('h3', null, title, info(help)), ...children)
}

export function info(text: string) {
  const icon = h('span', { class: 'ms-info', tabindex: '0', role: 'note', 'aria-label': text }, 'i')
  const tip = h('span', { class: 'ms-tip', role: 'tooltip' }, text)
  const open = () => {
    icon.closest('.ms')?.append(tip)
    const box = icon.getBoundingClientRect()
    const half = tip.offsetWidth / 2
    const center = Math.min(window.innerWidth - half - 8, Math.max(half + 8, box.left + box.width / 2))
    tip.style.left = `${String(center - half)}px`
    tip.style.top = `${String(box.bottom + 6)}px`
  }
  const close = () => {
    tip.remove()
  }
  icon.addEventListener('mouseenter', open)
  icon.addEventListener('focus', open)
  icon.addEventListener('mouseleave', close)
  icon.addEventListener('blur', close)
  return icon
}

export function caption(text: string, help: string) {
  return h('p', { class: 'ms-label' }, text, info(help))
}

export function muted(text: string) {
  return h('p', { class: 'ms-muted' }, text)
}

export function table(columns: (string | [string, string])[], rows: Child[]) {
  return h(
    'div',
    { class: 'ms-table' },
    h(
      'table',
      null,
      h(
        'thead',
        null,
        h(
          'tr',
          null,
          columns.map((column) =>
            typeof column === 'string' ? h('th', null, column) : h('th', null, column[0], info(column[1])),
          ),
        ),
      ),
      h('tbody', null, rows),
    ),
  )
}

export function shift(
  candidate: Candidate,
  label: string,
  warn: boolean,
  numeric: boolean,
  onclick: () => void,
) {
  const perUnit = numeric ? rate(candidate.transition) : null
  const parts = [
    `excess ${interval(candidate.transition.excess)}`,
    perUnit == null ? null : `${precise(perUnit)} per unit`,
    `p ${probability(candidate.adjusted_p_value)}`,
  ].filter((part) => part != null)
  return h(
    'button',
    { class: warn ? 'ms-shift ms-warn' : 'ms-shift', title: candidate.rationale, click: onclick },
    h('span', { class: 'ms-truncate' }, label),
    h(
      'span',
      { class: 'ms-muted' },
      parts.map((part, index) => [index > 0 && ' · ', h('span', null, part)]),
    ),
  )
}
