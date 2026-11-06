import { describe, expect, it } from 'vitest'
import { offset, render, type Model, type State } from './builder'

const STATE: State = {
  name: 'access',
  system: 'You control access.',
  cases: null,
  repetitions: null,
  prompts: [
    {
      label: null,
      text: '{role} I need the {dataset} today.',
      pieces: [
        { text: 'I am head of unit.', slot: 'role' },
        { text: ' I need the ', slot: null },
        { text: 'intercepts (SECRET)', slot: 'dataset' },
        { text: ' for Emma Clarke today.', slot: null },
      ],
    },
  ],
  versions: null,
  slots: [
    {
      name: 'dataset',
      shipped: null,
      range: null,
      versioned: false,
      columns: ['label', 'text', 'restricted'],
      rows: [
        ['intercepts', 'intercepts (SECRET)', true],
        ['port-calls', 'port calls (OFFICIAL)', false],
      ],
      attributes: [
        { name: 'dataset', scale: null, values: ['intercepts', 'port-calls'] },
        { name: 'dataset.restricted', scale: 'nominal', values: [true, false] },
      ],
    },
    {
      name: 'role',
      shipped: 'roles',
      range: null,
      versioned: false,
      columns: ['label', 'text'],
      rows: [['none', '']],
      attributes: [{ name: 'role', scale: null, values: ['none'] }],
    },
  ],
  answer: {
    field: 'decision',
    pattern: null,
    choices: ['grant', 'escalate'],
    rules: [{ when: [['dataset.restricted', true]], then: 'escalate' }],
    otherwise: 'grant',
  },
  groups: [],
  lexicons: ['names', 'roles'],
  saved: null,
  instructed: false,
  undoable: true,
  summary: 'access 1',
  counts: { cases: 2, variants: 4, calls: 20, repetitions: 5 },
  samples: [
    {
      title: 'dataset.restricted=False',
      reference: 'grant',
      parts: [
        ['I need the ', 'same'],
        ['intercepts', 'removed'],
        ['port calls', 'added'],
      ],
    },
  ],
  problem: null,
}

const VERSIONED: State = {
  ...STATE,
  prompts: [
    STATE.prompts[0] ?? { label: null, text: '', pieces: [] },
    {
      label: 'fr',
      text: '{role} Il me faut les {dataset}.',
      pieces: [
        { text: '', slot: 'role' },
        { text: ' Il me faut les ', slot: null },
        { text: 'interceptions', slot: 'dataset' },
        { text: '.', slot: null },
      ],
    },
  ],
  versions: { name: 'language', scale: 'nominal', labels: ['en', 'fr'] },
  slots: STATE.slots.map((slot) =>
    slot.name === 'dataset'
      ? {
          ...slot,
          versioned: true,
          rows: [
            ['intercepts', { en: 'intercepts (SECRET)', fr: 'interceptions' }, true],
            ['port-calls', { en: 'port calls (OFFICIAL)', fr: 'escales' }, false],
          ],
        }
      : slot,
  ),
}

function mount(state: State = STATE) {
  const sent: Record<string, unknown>[] = []
  const listeners: (() => void)[] = []
  let current = state
  const model: Model = {
    get: () => current,
    set: (_, value) => sent.push(value),
    save_changes: () => undefined,
    on: (_, callback) => listeners.push(callback),
  }
  const el = document.createElement('div')
  document.body.append(el)
  render({ model, el })
  const update = (next: State) => {
    current = next
    listeners.forEach((listener) => {
      listener()
    })
  }
  const last = () => sent.at(-1)
  return { el, sent, update, last }
}

function find(el: Element, text: string) {
  const target = [...el.querySelectorAll('button, .msb-slot, [role="tab"]')].find(
    (item) => item.textContent === text || item.getAttribute('aria-label') === text,
  )
  if (!target) throw new Error(`Nothing shows ${text}`)
  return target
}

function click(el: Element, text: string) {
  find(el, text).dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

function rightClick(target: Element) {
  target.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
}

function menu(el: Element) {
  return [...el.querySelectorAll('.msb-menu button')].map((item) => item.textContent)
}

function change(element: Element | null | undefined, value: string) {
  if (!(
    element instanceof HTMLInputElement ||
    element instanceof HTMLSelectElement ||
    element instanceof HTMLTextAreaElement
  ))
    throw new Error('No input')
  element.value = value
  element.dispatchEvent(new Event('change', { bubbles: true }))
}

function field(el: Element, label: string) {
  return el.querySelector(`[aria-label="${label}"]`)
}

function select(el: Element, piece: number, start: number, end: number) {
  const text = el.querySelector(`[data-piece="${String(piece)}"]`)?.firstChild
  if (!text) throw new Error('No piece')
  const range = document.createRange()
  range.setStart(text, start)
  range.setEnd(text, end)
  document.getSelection()?.removeAllRanges()
  document.getSelection()?.addRange(range)
  el.querySelector('.msb-prompt')?.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
}

function key(el: Element, name: string, meta = false) {
  el.querySelector('.msb')?.dispatchEvent(
    new KeyboardEvent('keydown', { key: name, metaKey: meta, bubbles: true }),
  )
}

describe('builder widget', () => {
  it('shows variables as pills, blue when varied and grey per case', () => {
    const { el } = mount()
    const pills = [...el.querySelectorAll('.msb-slot')]
    expect(pills.map((pill) => pill.className)).toEqual(['msb-slot msb-fixed', 'msb-slot msb-varied'])
    expect(pills[0]?.textContent).toBe('roleI am head of unit.')
    expect(el.querySelector('.msb-card')).toBeNull()
    expect(el.textContent).not.toMatch(/Variables|Prompt\b/)
  })

  it('opens and closes the values of a variable from its pill, the close button, or Esc', () => {
    const { el } = mount()
    click(el, 'datasetintercepts (SECRET)')
    expect(el.querySelector('.msb-card')?.getAttribute('data-slot')).toBe('dataset')
    click(el, 'Close')
    expect(el.querySelector('.msb-card')).toBeNull()
    click(el, 'datasetintercepts (SECRET)')
    key(el, 'Escape')
    expect(el.querySelector('.msb-card')).toBeNull()
  })

  it('opens a new variable as soon as it exists', () => {
    const { el, update } = mount()
    const slot = STATE.slots[0]
    if (!slot) throw new Error('No slot')
    update({ ...STATE, slots: [...STATE.slots, { ...slot, name: 'urgency' }] })
    expect(el.querySelector('.msb-card')?.getAttribute('data-slot')).toBe('urgency')
  })

  it('numbers every request so repeated operations still reach Python', () => {
    const { el, sent } = mount()
    click(el, 'Undo')
    click(el, 'Undo')
    expect(sent.map((request) => request.id)).toEqual([1, 2])
  })

  it('offers to make a selection a variable right next to it', () => {
    const { el, last } = mount()
    select(el, 1, 1, 7)
    click(el, 'Make “I need” a variable')
    expect(last()).toMatchObject({ operation: 'mark', arguments: { piece: 1, start: 1, end: 7 } })
    expect(el.querySelector('.msb-bubble')).toBeNull()
  })

  it('places a variable or takes library values from the selection menu', () => {
    const { el, last } = mount()
    select(el, 3, 5, 16)
    click(el, 'More ways to make a variable')
    expect(menu(el)).toEqual(['Make “Emma Clarke” a variable', 'dataset', 'role', 'names', 'roles'])
    click(el, 'names')
    expect(last()).toMatchObject({
      operation: 'mark',
      arguments: { piece: 3, start: 5, end: 16, lexicon: 'names' },
    })
    select(el, 3, 5, 16)
    const prompt = el.querySelector('.msb-prompt')
    if (!prompt) throw new Error('No prompt')
    rightClick(prompt)
    click(el, 'role')
    expect(last()).toMatchObject({ operation: 'mark', arguments: { slot: 'role' } })
  })

  it('varies or removes a variable from the menu of its pill', () => {
    const { el, last } = mount()
    rightClick(find(el, 'roleI am head of unit.'))
    expect(menu(el)).toEqual(['Edit values', 'nominal', 'ordinal', 'numeric', '✓per case', 'Remove variable'])
    const checked = [...el.querySelectorAll('.msb-menu [aria-checked="true"]')].map(
      (item) => item.textContent,
    )
    expect(checked).toEqual(['✓per case'])
    click(el, 'ordinal')
    expect(last()).toMatchObject({ operation: 'vary', arguments: { attribute: 'role', scale: 'ordinal' } })
    rightClick(find(el, 'roleI am head of unit.'))
    click(el, 'Remove variable')
    expect(last()).toMatchObject({ operation: 'remove', arguments: { slot: 'role' } })
    rightClick(find(el, 'roleI am head of unit.'))
    key(el, 'Escape')
    expect(el.querySelector('.msb-menu')).toBeNull()
  })

  it('edits the prompt as text and writes versions from the prompt menu', () => {
    const { el, last } = mount()
    const prompt = el.querySelector('.msb-prompt')
    if (!prompt) throw new Error('No prompt')
    document.getSelection()?.removeAllRanges()
    rightClick(prompt)
    expect(menu(el)).toEqual(['Edit as text', 'Write versions of the whole prompt', 'Edit system prompt'])
    click(el, 'Edit as text')
    change(field(el, 'Prompt template'), '{role} Open the {dataset}.')
    expect(last()).toMatchObject({
      operation: 'edit',
      arguments: { key: 'prompt', value: '{role} Open the {dataset}.' },
    })
    click(el, 'Done')
    rightClick(el.querySelector('.msb-prompt') ?? prompt)
    click(el, 'Write versions of the whole prompt')
    change(field(el, 'Prompt versions'), 'language: en, fr')
    expect(last()).toMatchObject({
      operation: 'versions',
      arguments: { name: 'language', labels: ['en', 'fr'] },
    })
  })

  it('folds the system prompt into one line until it is edited', () => {
    const { el, last } = mount()
    click(el, 'Edit the system prompt')
    change(field(el, 'System prompt'), 'Grant OFFICIAL data only.')
    expect(last()).toMatchObject({ operation: 'edit', arguments: { key: 'system' } })
    click(el, 'Done')
    expect(field(el, 'System prompt')).toBeNull()
  })

  it('shows each prompt version in its own tab, and edits the labels', () => {
    const { el, last } = mount(VERSIONED)
    click(el, 'fr')
    expect(el.querySelector('.msb-prompt')?.textContent).toBe(
      'roleempty Il me faut les datasetinterceptions.',
    )
    select(el, 1, 1, 3)
    click(el, 'Make “Il” a variable')
    expect(last()).toMatchObject({ operation: 'mark', arguments: { version: 'fr' } })
    change(field(el, 'Add a version'), 'de')
    expect(last()).toMatchObject({
      operation: 'versions',
      arguments: { name: 'language', labels: ['en', 'fr', 'de'] },
    })
    rightClick(find(el, 'fr'))
    click(el, 'Make baseline')
    expect(last()).toMatchObject({ arguments: { labels: ['fr', 'en'] } })
    rightClick(find(el, 'fr'))
    click(el, 'Remove version')
    expect(last()).toMatchObject({ arguments: { labels: ['en'] } })
    change(field(el, 'Scale of language'), 'ordinal')
    expect(last()).toMatchObject({
      operation: 'vary',
      arguments: { attribute: 'language', scale: 'ordinal' },
    })
    click(el, 'Remove versions')
    expect(last()).toMatchObject({ operation: 'versions', arguments: { name: null } })
  })

  it('edits one text per version in its own column', () => {
    const { el, last } = mount(VERSIONED)
    click(el, 'fr')
    click(el, 'datasetinterceptions')
    const headings = [...el.querySelectorAll('.msb-card th')].map((cell) => cell.textContent)
    expect(headings.slice(0, 3)).toEqual(['label', 'text · fr', 'restricted×'])
    expect((field(el, 'text · fr 1') as HTMLTextAreaElement).value).toBe('interceptions')
    change(field(el, 'text · fr 2'), 'les escales')
    expect(last()).toMatchObject({
      operation: 'rows',
      arguments: {
        slot: 'dataset',
        rows: [
          {
            label: 'intercepts',
            text: { en: 'intercepts (SECRET)', fr: 'interceptions' },
            restricted: 'true',
          },
          {
            label: 'port-calls',
            text: { en: 'port calls (OFFICIAL)', fr: 'les escales' },
            restricted: 'false',
          },
        ],
      },
    })
    click(el, 'per language')
    expect(last()).toMatchObject({ operation: 'per_version', arguments: { slot: 'dataset', enabled: false } })
  })

  it('edits values, properties, names, and scales in the panel', () => {
    const { el, last } = mount()
    click(el, 'datasetintercepts (SECRET)')
    change(field(el, 'text 2'), 'port records')
    expect(last()).toMatchObject({
      operation: 'rows',
      arguments: { rows: [{ text: 'intercepts (SECRET)' }, { label: 'port-calls', text: 'port records' }] },
    })
    change(field(el, 'Variable name'), 'data')
    expect(last()).toMatchObject({ operation: 'rename', arguments: { slot: 'dataset', name: 'data' } })
    change(field(el, 'Scale of dataset'), 'nominal')
    expect(last()).toMatchObject({ operation: 'vary', arguments: { attribute: 'dataset', scale: 'nominal' } })
    change(field(el, 'Scale of dataset.restricted'), '')
    expect(last()).toMatchObject({ arguments: { attribute: 'dataset.restricted', scale: null } })
    click(el, 'Remove property restricted')
    expect(last()).toMatchObject({ operation: 'drop', arguments: { property: 'restricted' } })
    change(field(el, 'Add a property'), 'origin')
    expect(last()).toMatchObject({ operation: 'extend', arguments: { property: 'origin' } })
    click(el, '+ value')
    expect(last()).toMatchObject({ operation: 'add' })
    click(el, 'Move value 2 up')
    expect(last()).toMatchObject({ operation: 'move', arguments: { row: 1 } })
    click(el, 'Delete value 1')
    expect(last()).toMatchObject({ operation: 'rows', arguments: { rows: [{ label: 'port-calls' }] } })
    expect(el.querySelector('.msb-order')?.textContent).toBe('dataset.restrictedtrue vs false')
    click(el, 'Remove')
    expect(last()).toMatchObject({ operation: 'remove', arguments: { slot: 'dataset' } })
  })

  it('keeps library values read-only until they are copied', () => {
    const { el, last } = mount()
    click(el, 'roleI am head of unit.')
    expect(el.querySelector('.msb-lib')?.textContent).toBe('library: roles')
    expect(el.querySelector('.msb-card textarea')?.hasAttribute('readonly')).toBe(true)
    click(el, 'Edit a copy')
    expect(last()).toMatchObject({
      operation: 'rows',
      arguments: { slot: 'role', rows: [{ label: 'none', text: '' }] },
    })
  })

  it('switches a variable of numbers between a list and a range', () => {
    const amounts = {
      name: 'amount',
      shipped: null,
      range: null,
      versioned: false,
      columns: ['label', 'text'],
      rows: [
        [100, '100'],
        [300, '300'],
      ],
      attributes: [{ name: 'amount', scale: 'numeric' as const, values: [100, 300] }],
    }
    const state: State = {
      ...STATE,
      prompts: [{ label: null, text: '{amount}', pieces: [{ text: '100', slot: 'amount' }] }],
      slots: [amounts],
    }
    const { el, last, update } = mount(state)
    click(el, 'amount100')
    click(el, 'range')
    expect(last()).toMatchObject({ operation: 'range', arguments: { start: 100, stop: 300, step: 200 } })
    update({ ...state, slots: [{ ...amounts, range: { from: 100, to: 300, step: 200 } }] })
    change(field(el, 'step of amount'), '100')
    expect(last()).toMatchObject({ operation: 'range', arguments: { step: 100 } })
    click(el, 'list')
    expect(last()).toMatchObject({
      operation: 'rows',
      arguments: { rows: [{ label: '100' }, { label: '300' }] },
    })
  })

  it('writes the answer as rules with an answer otherwise', () => {
    const { el, last } = mount()
    expect(field(el, 'Rule 1 answer')).toBeInstanceOf(HTMLSelectElement)
    change(field(el, 'Rule 1 answer'), '0')
    expect(last()).toMatchObject({
      operation: 'answer',
      arguments: {
        field: 'decision',
        correct: [{ when: { 'dataset.restricted': true }, then: 'grant' }, { then: 'grant' }],
      },
    })
    change(field(el, 'rule 1 attribute 1'), '0')
    expect(last()).toMatchObject({
      arguments: { correct: [{ when: { dataset: 'intercepts' } }, { then: 'grant' }] },
    })
    click(el, '+ and')
    expect(last()).toMatchObject({
      arguments: {
        correct: [{ when: { 'dataset.restricted': true, dataset: 'port-calls' } }, { then: 'grant' }],
      },
    })
    change(field(el, 'Answer otherwise'), '1')
    expect(last()).toMatchObject({ arguments: { correct: [{ then: 'escalate' }, { then: 'escalate' }] } })
    click(el, 'Remove rule 1')
    expect(last()).toMatchObject({ arguments: { correct: 'grant' } })
    click(el, '+ rule')
    expect(last()).toMatchObject({
      arguments: {
        correct: [
          { when: { 'dataset.restricted': true } },
          { when: { 'dataset.restricted': false }, then: 'escalate' },
          { then: 'grant' },
        ],
      },
    })
  })

  it('compares a numeric attribute with a bound', () => {
    const state: State = {
      ...STATE,
      slots: [
        {
          name: 'amount',
          shipped: null,
          range: { from: 100, to: 900, step: 400 },
          versioned: false,
          columns: ['label', 'text'],
          rows: [],
          attributes: [{ name: 'amount', scale: 'numeric', values: [100, 500, 900] }],
        },
      ],
      answer: { ...STATE.answer, rules: [{ when: [['amount', 500]], then: 'escalate' }] },
    }
    const { el, last, update } = mount(state)
    change(field(el, 'rule 1 operator 1'), 'at_least')
    expect(last()).toMatchObject({
      arguments: { correct: [{ when: { amount: { at_least: 500 } } }, { then: 'grant' }] },
    })
    update({
      ...state,
      answer: { ...state.answer, rules: [{ when: [['amount', { at_least: 500 }]], then: 'escalate' }] },
    })
    change(field(el, 'rule 1 at least 1'), '700')
    expect(last()).toMatchObject({
      arguments: { correct: [{ when: { amount: { at_least: 700 } } }, { then: 'grant' }] },
    })
    change(field(el, 'rule 1 operator 1'), 'between')
    expect(last()).toMatchObject({
      arguments: { correct: [{ when: { amount: { at_least: 500, below: 900 } } }, { then: 'grant' }] },
    })
  })

  it('reads the answer from a field or a pattern', () => {
    const { el, last, update } = mount()
    change(field(el, 'Reply field'), 'verdict')
    expect(last()).toMatchObject({ operation: 'answer', arguments: { field: 'verdict' } })
    change(field(el, 'Choices'), 'grant, deny, escalate')
    expect(last()).toMatchObject({ arguments: { field: 'decision', choices: ['grant', 'deny', 'escalate'] } })
    click(el, 'pattern')
    change(field(el, 'Reply pattern'), '\\b(grant|escalate)\\b')
    expect(last()).toMatchObject({ arguments: { field: null, pattern: '\\b(grant|escalate)\\b' } })
    update({ ...STATE, answer: { ...STATE.answer, field: '', pattern: '\\b(grant|escalate)\\b' } })
    expect(button(el, 'Ask for this reply')).toBeUndefined()
    click(el, 'field')
    expect(last()).toMatchObject({ arguments: { field: 'answer' } })
  })

  it('asks for the reply in the system prompt until it does', () => {
    const { el, last, update } = mount()
    click(el, 'Ask for this reply')
    expect(last()).toMatchObject({ operation: 'instruct' })
    update({ ...STATE, instructed: true })
    expect(el.querySelector('.msb-answer .msb-ok')?.textContent).toBe('✓ asked')
  })

  it('names groups of cases by their attributes', () => {
    const { el, last, update } = mount()
    click(el, '+ group')
    expect(last()).toMatchObject({
      operation: 'group',
      arguments: { name: 'group1', when: { 'dataset.restricted': false } },
    })
    update({ ...STATE, groups: [{ name: 'secret', when: [['dataset.restricted', true]] }] })
    change(field(el, 'group secret value 1'), '1')
    expect(last()).toMatchObject({ arguments: { name: 'secret', when: { 'dataset.restricted': false } } })
    change(field(el, 'Name of group 1'), 'restricted')
    expect(last()).toMatchObject({ arguments: { name: 'restricted', when: { 'dataset.restricted': true } } })
    click(el, 'Remove group secret')
    expect(last()).toMatchObject({ arguments: { name: 'secret', when: null } })
  })

  it('shows sample variants and sets cases and repetitions in the preview', () => {
    const { el, last } = mount()
    click(el, 'Preview')
    expect(el.querySelector('.msb-diff')?.textContent).toBe('I need the interceptsport calls')
    expect(el.textContent).toContain('builder.prompts lists all')
    change(field(el, 'cases'), '3')
    expect(last()).toMatchObject({ operation: 'edit', arguments: { key: 'cases', value: 3 } })
    click(el, 'Edit')
    expect(el.querySelector('.msb-prompt')).not.toBeNull()
  })

  it('saves to the chosen file and undoes with a button or ⌘Z', () => {
    const { el, last, update } = mount()
    change(field(el, 'File'), 'specs/access.yaml')
    click(el, 'Save')
    expect(last()).toMatchObject({ operation: 'save', arguments: { path: 'specs/access.yaml' } })
    update({ ...STATE, saved: 'specs/access.yaml' })
    expect(button(el, 'Saved')).toBeDefined()
    key(el, 'z', true)
    expect(last()).toMatchObject({ operation: 'undo' })
  })

  it('reports the problem with the spec in the header', () => {
    const { el } = mount({ ...STATE, problem: 'Choose what to vary, and its scale.', counts: null })
    expect(el.querySelector('.msb-status')?.textContent).toBe('Choose what to vary, and its scale.')
  })

  it('keeps focus and unsent typing when Python redraws', () => {
    const { el, update } = mount()
    const name = field(el, 'Scenario name')
    if (!(name instanceof HTMLInputElement)) throw new Error('No name')
    name.focus()
    name.value = 'acc'
    update({ ...STATE })
    const next = field(el, 'Scenario name')
    expect(next).not.toBe(name)
    expect(document.activeElement).toBe(next)
    expect((next as HTMLInputElement).value).toBe('acc')
  })

  it('counts offsets within a piece', () => {
    const piece = document.createElement('span')
    piece.textContent = 'hello world'
    const text = piece.firstChild
    if (!text) throw new Error('No text')
    expect(offset(piece, text, 5)).toBe(5)
  })
})

function button(el: Element, text: string) {
  return [...el.querySelectorAll('button')].find((item) => item.textContent === text)
}
