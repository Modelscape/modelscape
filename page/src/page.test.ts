import { beforeAll, describe, expect, it } from 'vitest'
import { casesOf, OUTPUTS, REPORT } from './fixture'
import { render } from './page'
import type { Outputs, Report } from './types'

function mount(report: Report = REPORT, outputs: Outputs | null = OUTPUTS) {
  const el = document.createElement('div')
  render(el, { report, outputs })
  return el
}

const text = (el: Element) => el.textContent.replace(/\s+/g, ' ')

const click = (el: Element, selector: string) => {
  const target = el.querySelector(selector)
  if (!target) throw new Error(`No element matches ${selector}`)
  target.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

beforeAll(() => {
  Element.prototype.scrollIntoView = () => undefined
})

describe('report page', () => {
  it('shows the scorecard, every axis, divergence, and provenance', () => {
    const el = mount()
    expect(text(el)).toContain('pressure v4')
    expect(el.querySelector('.ms-brand')?.getAttribute('href')).toBe(
      'https://github.com/Modelscape/modelscape',
    )
    expect(el.querySelectorAll('.ms-card')).toHaveLength(3)
    expect(text(el)).toContain('model-b differs from model-a beyond noise in 0 of 0 comparisons')
    expect(text(el)).toContain('a-2026-10')
    expect(text(el)).toContain('63,480')
    expect(text(el)).toContain('Answered')
    expect(text(el)).toContain('0.98')
  })

  it('states the findings in words and opens the outputs behind a flaw', () => {
    const el = mount()
    const items = [...el.querySelectorAll('.ms-finding li')].map(text)
    expect(items).toEqual([
      '✗Answers shift with pressure, which should not matter: 4 → 5.',
      '✓Answers follow dataset.restricted, as they should.',
    ])
    expect(el.querySelector('tbody td.ms-bad')?.textContent).toBe('1')
    click(el, '.ms-step')
    expect(text(el.querySelector('.ms-inspector') ?? el)).toContain('model-a · pressure: 4 → 5')
  })

  it('says when a model ignores what should matter or gives unreadable answers', () => {
    const report = structuredClone(REPORT)
    const [card] = report.scorecards
    if (!card) throw new Error('No scorecard')
    for (const axis of card.axes) axis.shifts = []
    card.answered = 0.7
    expect([...mount(report).querySelectorAll('.ms-finding li')].map(text)).toEqual([
      '✗Answers do not follow dataset.restricted, which should change them.',
      '✗Only 70% of outputs had a readable answer; the rest count as wrong.',
      '✓No shifts on axes that should not matter.',
    ])
  })

  it('marks shifts on invariant axes only', () => {
    const shifts = [...mount().querySelectorAll('.ms-shift')]
    expect(shifts.map((item) => item.classList.contains('ms-warn'))).toEqual([true, false])
  })

  it('shows the outputs behind a shift on both sides', () => {
    const el = mount()
    click(el, '.ms-shift')
    expect(text(el.querySelector('.ms-stats') ?? el)).toContain('p0.002')
    expect(el.querySelectorAll('.ms-side')).toHaveLength(2)
    expect(el.querySelectorAll('.ms-output')).toHaveLength(4)
    expect(text(el.querySelector('.ms-side') ?? el)).toContain('pressure=4')
    expect(el.querySelector('details pre')?.textContent).toBe('Apply the data-access policy.')
  })

  it('scores the outputs behind an accuracy', () => {
    const el = mount()
    click(el, '.ms-selectable')
    expect(
      [...(el.querySelector('.ms-inspector')?.querySelectorAll('.ms-good, .ms-bad') ?? [])].map(
        (item) => item.textContent,
      ),
    ).toEqual(['✓', '✗'])
  })

  it('shows the cases that changed most first, and the rest on request', () => {
    const names = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    const report = structuredClone(REPORT)
    for (const shift of report.scorecards.flatMap((card) => card.axes.flatMap((axis) => axis.shifts))) {
      shift.transition.per_case = names.map((name, index) => ({
        case: name,
        between: 0.5,
        within: 0.1,
        excess: index / 10,
      }))
      shift.transition.outputs = names.flatMap((_, index) => [
        [2 * index, null],
        [2 * index + 1, null],
      ])
    }
    const el = mount(report, casesOf(names))
    click(el, '.ms-shift')
    const shown = () => [...el.querySelectorAll('.ms-case h4')].map((item) => item.textContent)
    expect(shown()).toEqual(['g', 'f', 'e', 'd', 'c'])
    click(el, '.ms-more')
    expect(shown()).toEqual(['g', 'f', 'e', 'd', 'c', 'b', 'a'])
    expect(el.querySelector('.ms-more')).toBeNull()
  })

  it('plots accuracy per axis value with its interval', () => {
    const el = mount()
    const rows = [...el.querySelectorAll('.ms-card')][0]?.querySelectorAll('.ms-mark') ?? []
    expect(rows).toHaveLength(2)
    expect(rows[0]?.querySelector('title')?.textContent).toBe('model-a · pressure=0: 1.00 [0.90, 1.00]')
    expect(el.querySelector('.ms-legend')).toBeNull()
  })

  it('compares every target of a group in one chart with a legend', () => {
    const report = structuredClone(REPORT)
    const [card] = report.scorecards
    if (!card) throw new Error('No scorecard')
    report.scorecards.push({ ...structuredClone(card), target: 'model-b' })
    const el = mount(report)
    expect([...el.querySelectorAll('.ms-legend > span')].map((item) => item.textContent)).toEqual([
      'model-a',
      'model-b',
    ])
    expect(el.querySelector('.ms-card')?.querySelectorAll('.ms-mark')).toHaveLength(4)
    expect(el.querySelectorAll('tr.ms-active, tr.ms-clickable')).toHaveLength(0)
  })

  it('selects a group of scorecards when there are several', () => {
    const report = structuredClone(REPORT)
    const [card] = report.scorecards
    if (!card) throw new Error('No scorecard')
    report.scorecards.push({ ...structuredClone(card), group: 'sensitive' })
    const el = mount(report)
    click(el, 'tr.ms-clickable')
    expect(text(el)).toContain('Axes · sensitive')
    expect(
      [...(el.querySelector('tbody')?.querySelectorAll('tr') ?? [])].map((row) => row.className),
    ).toEqual(['ms-clickable', 'ms-active'])
  })

  it('shows how the cases behind a number are spread', () => {
    const el = mount()
    click(el, '.ms-shift')
    expect(text(el.querySelector('.ms-figure') ?? el)).toContain('Excess change per case')
    expect(el.querySelectorAll('.ms-bin')).toHaveLength(21)
    expect(el.querySelector('.ms-bin title')?.textContent).toBe('excess -1.0: 0 cases')
  })

  it('plots every compared coordinate and opens the ones that differ', () => {
    const report = structuredClone(REPORT)
    const shifted = report.scorecards[0]?.axes[0]?.shifts[0]
    if (!shifted) throw new Error('No shift')
    const quiet = { ...shifted.transition, end: { pressure: 1, 'dataset.restricted': true } }
    report.divergences = [
      { first: 'model-a', second: 'model-b', contrasts: [quiet, shifted.transition], candidates: [shifted] },
    ]
    const el = mount(report)
    const card = [...el.querySelectorAll('article')].find((item) => item.textContent.includes('differs from'))
    const marks = [...(card?.querySelectorAll('.ms-mark') ?? [])]
    expect(marks.map((item) => item.classList.contains('ms-selectable'))).toEqual([false, true])
    marks[1]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(text(el.querySelector('.ms-inspector') ?? el)).toContain('model-b vs model-a')
  })

  it('gives the excess change per unit only of a numeric step larger than one', () => {
    const report = structuredClone(REPORT)
    const axis = report.scorecards[0]?.axes[0]
    const shifted = axis?.shifts[0]?.transition
    if (!axis || !shifted) throw new Error('No shift')
    expect(text(mount(report))).not.toContain('per unit')
    shifted.start = { ...shifted.start, pressure: 3 }
    shifted.end = { ...shifted.end, pressure: 5 }
    expect(text(mount(report))).not.toContain('per unit')
    axis.scale = 'numeric'
    expect(text(mount(report).querySelector('.ms-shift') ?? document.body)).toContain('0.28 per unit')
  })

  it('shows the scale of every axis', () => {
    const badges = [...mount(REPORT).querySelectorAll('.ms-card-header')].map((header) =>
      [...header.querySelectorAll('.ms-badge')].map((badge) => badge.textContent),
    )
    expect(badges).toEqual([
      ['ordinal', 'invariant'],
      ['nominal', 'causal'],
    ])
  })

  it('compares where the answer flips with where it should', () => {
    const report = structuredClone(REPORT)
    const axis = report.scorecards[0]?.axes[0]
    if (!axis) throw new Error('No axis')
    axis.threshold = {
      reference: 2.5,
      offset: { value: 1, lower: 0.5, upper: 1.5 },
      width: { value: 0.4, lower: 0.2, upper: 0.8 },
    }
    const card = mount(report).querySelector('.ms-card')
    if (!card) throw new Error('No card')
    expect(text(card)).toContain('Where the answer flips')
    expect(text(card)).toContain('width 0.40 [0.20, 0.80]')
    const titles = [...card.querySelectorAll('.ms-mark title')].map((item) => item.textContent)
    expect(titles.slice(-2)).toEqual(['model-a: 3.50 [3.00, 4.00]', 'The correct answer flips at 2.50'])
  })

  it('rounds large thresholds and small rates to readable numbers', () => {
    const report = structuredClone(REPORT)
    const axis = report.scorecards[0]?.axes[0]
    const shifted = axis?.shifts[0]?.transition
    if (!axis || !shifted) throw new Error('No axis')
    axis.scale = 'numeric'
    axis.threshold = {
      reference: 9500,
      offset: { value: 500.4, lower: 100.2, upper: 900.9 },
      width: { value: 1029.63, lower: 607.14, upper: 1488.47 },
    }
    shifted.start = { ...shifted.start, pressure: 9000 }
    shifted.end = { ...shifted.end, pressure: 10000 }
    const card = mount(report).querySelector('.ms-card')
    if (!card) throw new Error('No card')
    expect(text(card)).toContain('width 1,030 [607, 1,488]')
    expect(text(card)).toContain('0.00055 per unit')
  })

  it('says when the answer flips away from where it should', () => {
    const report = structuredClone(REPORT)
    const axis = report.scorecards[0]?.axes[1]
    if (!axis) throw new Error('No axis')
    axis.threshold = {
      reference: 9500,
      offset: { value: 2000, lower: 1500, upper: 2500 },
      width: null,
    }
    expect([...mount(report).querySelectorAll('.ms-finding li')].map(text)).toContain(
      '✗Answers flip on dataset.restricted at 11,500 [11,000, 12,000], but should flip at 9,500.',
    )
  })

  it('says when the answer never flips', () => {
    const report = structuredClone(REPORT)
    const axis = report.scorecards[0]?.axes[0]
    if (!axis) throw new Error('No axis')
    axis.threshold = { reference: 2.5, offset: null, width: null }
    expect(text(mount(report))).toContain('no flip within the axis')
  })

  it('closes the inspector', () => {
    const el = mount()
    click(el, '.ms-shift')
    click(el, '.ms-close')
    expect(el.querySelector('.ms-inspector')).toBeNull()
  })

  it('says how to include outputs when the page has none', () => {
    const el = mount(REPORT, null)
    click(el, '.ms-shift')
    expect(text(el)).toContain('modelscape view report.json --store modelscape.db')
  })
})
