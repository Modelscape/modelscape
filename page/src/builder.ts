import { h } from './dom'
import { logo } from './logo'
import styles from './builder.css'
import type { Part } from './types'

type Value = string | number | boolean
type Texts = Record<string, string>
type Cell = Value | Texts
type Scale = 'nominal' | 'ordinal' | 'numeric'
type Operator = 'is' | 'at_least' | 'below' | 'between'
type Condition = Value | Bound
type When = [string, Condition][]

interface Attribute {
  name: string
  scale: Scale | null
  values: Value[]
}
interface Span {
  from: number
  to: number
  step: number
}
interface Bound {
  at_least?: number
  below?: number
}
interface Piece {
  text: string
  slot: string | null
}

const SCALES: Scale[] = ['nominal', 'ordinal', 'numeric']
const OPERATORS: Record<Operator, string> = { is: 'is', at_least: '≥', below: '<', between: 'between' }
const ORDERS: Record<Scale, string> = {
  nominal: 'Each value is compared with the baseline',
  ordinal: 'Each value is compared with the next, in this order',
  numeric: 'Each number is compared with the next, and by the size of the step',
}
const DOCS = 'https://modelscape.github.io/modelscape/builder/'

export interface State {
  name: string
  system: string
  cases: number | null
  repetitions: number | null
  prompts: { label: Value | null; text: string; pieces: Piece[] }[]
  versions: { name: string; scale: Scale | null; labels: Value[] } | null
  slots: {
    name: string
    shipped: string | null
    range: Span | null
    versioned: boolean
    columns: string[]
    rows: Cell[][]
    attributes: Attribute[]
  }[]
  answer: {
    field: string
    pattern: string | null
    choices: Value[]
    rules: { when: When; then: Value }[]
    otherwise: Value | null
  }
  groups: { name: string; when: When }[]
  lexicons: string[]
  saved: string | null
  instructed: boolean
  undoable: boolean
  summary: string | null
  counts: { cases: number; variants: number; calls: number; repetitions: number } | null
  samples: { title: string; reference: Value; parts: Part[] }[]
  problem: string | null
}

export interface Model {
  get(name: 'state'): State
  set(name: 'request', value: Record<string, unknown>): void
  save_changes(): void
  on(event: 'change:state', callback: () => void): void
}

interface Caret {
  piece: number
  start: number
  end: number
  text: string
}

type Item = { label: string; run: () => void; checked?: boolean } | { heading: string }
type Slot = State['slots'][number]
type Rule = State['answer']['rules'][number]

export function render({ model, el }: { model: Model; el: HTMLElement }) {
  const root = el
  let requests = 0
  let view: 'Edit' | 'Preview' = 'Edit'
  let version = 0
  let active: string | null = null
  let known: string[] | null = null
  let editing = false
  let system = false
  let versioning = false
  let reading: 'field' | 'pattern' | null = null
  let path: string | null = null
  let caret: Caret | null = null

  const send = (operation: string, args: Record<string, unknown> = {}) => {
    requests += 1
    model.set('request', { id: requests, operation, arguments: args })
    model.save_changes()
  }

  const draw = () => {
    const state = model.get('state')
    const names = state.slots.map((slot) => slot.name)
    const added = names.find((name) => known !== null && !known.includes(name))
    if (added !== undefined) active = added
    if (active !== null && !names.includes(active)) active = null
    known = names
    if (version >= state.prompts.length) version = 0
    const kept = remembered(root)
    caret = null
    const frame = h(
      'div',
      { class: 'msb', mousedown: dismiss },
      header(state),
      view === 'Edit' ? [prompt(state), panel(state), answer(state)] : preview(state),
    )
    frame.addEventListener('keydown', keys)
    root.replaceChildren(h('style', null, styles), frame)
    root.querySelectorAll<HTMLTextAreaElement>('textarea.msb-cell').forEach(fit)
    restore(root, kept)
  }

  const keys = (event: KeyboardEvent) => {
    const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement
    if (event.key === 'Escape') {
      if (closeMenu()) return
      if (versioning || editing || active !== null) {
        versioning = false
        editing = false
        active = null
        draw()
      }
    } else if ((event.metaKey || event.ctrlKey) && event.key === 'z' && !typing) {
      event.preventDefault()
      if (model.get('state').undoable) send('undo')
    }
  }

  const dismiss = (event: MouseEvent) => {
    const menu = root.querySelector('.msb-menu')
    if (menu && event.target instanceof Node && !menu.contains(event.target)) menu.remove()
    const bubble = root.querySelector('.msb-bubble')
    if (bubble && event.target instanceof Node && !bubble.contains(event.target)) bubble.remove()
  }

  const closeMenu = () => {
    const open = root.querySelectorAll('.msb-menu, .msb-bubble')
    open.forEach((item) => {
      item.remove()
    })
    return open.length > 0
  }

  const place = (element: HTMLElement, x: number, y: number) => {
    const frame = root.querySelector('.msb')?.getBoundingClientRect()
    element.style.left = `${String(x - (frame?.left ?? 0))}px`
    element.style.top = `${String(y - (frame?.top ?? 0))}px`
    root.querySelector('.msb')?.append(element)
  }

  const menu = (x: number, y: number, items: Item[]) => {
    closeMenu()
    const checks = items.some((item) => 'checked' in item)
    const list = h(
      'div',
      { class: 'msb-menu', role: 'menu' },
      items.map((item) =>
        'heading' in item
          ? h('div', { class: item.heading ? 'msb-menu-heading' : 'msb-menu-rule' }, item.heading)
          : h(
              'button',
              {
                type: 'button',
                role: item.checked === undefined ? 'menuitem' : 'menuitemradio',
                'aria-checked': item.checked === undefined ? null : String(item.checked),
                click: () => {
                  closeMenu()
                  item.run()
                },
              },
              checks && h('span', { class: 'msb-check' }, item.checked ? '✓' : ''),
              item.label,
            ),
      ),
    )
    place(list, x, y)
    list.querySelector('button')?.focus()
  }

  const header = (state: State) => {
    const file = path ?? `${state.name || 'scenario'}.yaml`
    const status = state.problem
      ? h('span', { class: 'msb-status msb-warn', title: state.problem }, state.problem)
      : state.counts &&
        h(
          'span',
          { class: 'msb-status msb-ok' },
          `${plural(state.counts.variants, 'variant')} · ${plural(state.counts.calls, 'call')}`,
        )
    return h(
      'header',
      { class: 'msb-row msb-header' },
      h(
        'a',
        { class: 'msb-logo', href: DOCS, target: '_blank', rel: 'noopener', 'aria-label': 'modelscape' },
        logo(),
      ),
      input(
        state.name,
        'name',
        'Scenario name',
        (value) => {
          send('edit', { key: 'name', value })
        },
        'msb-title',
      ),
      status,
      h('span', { class: 'msb-grow' }),
      segmented(view, ['Edit', 'Preview'], 'View', (chosen) => {
        view = chosen
        draw()
      }),
      button(
        'Undo',
        () => {
          send('undo')
        },
        { quiet: true, disabled: !state.undoable, title: 'Undo (⌘Z)' },
      ),
      h(
        'span',
        { class: 'msb-save' },
        input(
          file,
          'file',
          'File',
          (value) => {
            path = value
          },
          'msb-file',
        ),
        button(
          state.saved ? 'Saved' : 'Save',
          () => {
            send('save', { path: path ?? file })
          },
          {
            primary: !state.saved,
            title: state.saved ? `Saved to ${state.saved}` : 'Write the spec as YAML',
          },
        ),
      ),
    )
  }

  const prompt = (state: State) => {
    const shown = state.prompts[version] ?? state.prompts[0]
    const label = shown?.label ?? null
    const rich = h(
      'div',
      { class: 'msb-prompt', 'aria-label': 'Prompt', contextmenu: promptMenu(state) },
      (shown?.pieces ?? []).map((piece, index) =>
        piece.slot === null ? h('span', { 'data-piece': String(index) }, piece.text) : pill(state, piece),
      ),
    )
    rich.addEventListener('mouseup', (event) => {
      caret = selected(rich)
      if (caret) bubble(state, event.clientX, event.clientY)
    })
    const body = editing
      ? textArea(shown?.text ?? '', 'prompt', 'Prompt template', (text) => {
          if (version === 0) send('edit', { key: 'prompt', value: text })
          else send('version', { label, text })
        })
      : rich
    return h(
      'section',
      { class: 'msb-section' },
      systemLine(state),
      versionBar(state),
      h(
        'div',
        { class: 'msb-frame' },
        body,
        editing &&
          h(
            'div',
            { class: 'msb-row msb-small' },
            h('span', { class: 'msb-muted' }, 'Write a variable as {name} and a literal brace twice.'),
            h('span', { class: 'msb-grow' }),
            button(
              'Done',
              () => {
                editing = false
                draw()
              },
              { quiet: true },
            ),
          ),
      ),
    )
  }

  const bubble = (state: State, x: number, y: number) => {
    closeMenu()
    const chosen = caret
    if (!chosen) return
    const element = h(
      'div',
      { class: 'msb-bubble' },
      button(`Make “${short(chosen.text, 20)}” a variable`, () => {
        closeMenu()
        mark(state, chosen)
      }),
      button(
        '▾',
        () => {
          const box = element.getBoundingClientRect()
          menu(box.left, box.bottom + 4, selectionItems(state, chosen))
        },
        { quiet: true, label: 'More ways to make a variable' },
      ),
    )
    place(element, x, y + 12)
  }

  const mark = (state: State, chosen: Caret, extra: Record<string, unknown> = {}) => {
    const label = state.prompts[version]?.label ?? null
    send('mark', {
      piece: chosen.piece,
      start: chosen.start,
      end: chosen.end,
      ...(label === null ? {} : { version: label }),
      ...extra,
    })
  }

  const selectionItems = (state: State, chosen: Caret): Item[] => [
    {
      label: `Make “${short(chosen.text, 24)}” a variable`,
      run: () => {
        mark(state, chosen)
      },
    },
    ...(state.slots.length > 0
      ? [
          { heading: 'Place a variable' },
          ...state.slots.map((slot) => ({
            label: slot.name,
            run: () => {
              mark(state, chosen, { slot: slot.name })
            },
          })),
        ]
      : []),
    { heading: 'Values from the library' },
    ...state.lexicons.map((name) => ({
      label: name,
      run: () => {
        mark(state, chosen, { lexicon: name })
      },
    })),
  ]

  const promptMenu = (state: State) => (event: MouseEvent) => {
    event.preventDefault()
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('.msb-slot') : null
    const chosen = caret ?? selected(event.currentTarget as HTMLElement)
    if (target?.dataset.slot) menu(event.clientX, event.clientY, pillItems(state, target.dataset.slot))
    else if (chosen) menu(event.clientX, event.clientY, selectionItems(state, chosen))
    else menu(event.clientX, event.clientY, promptItems(state))
  }

  const promptItems = (state: State): Item[] => [
    {
      label: 'Edit as text',
      run: () => {
        editing = true
        draw()
      },
    },
    state.versions
      ? {
          label: 'Remove versions',
          run: () => {
            send('versions', { name: null, labels: [] })
          },
        }
      : {
          label: 'Write versions of the whole prompt',
          run: () => {
            versioning = true
            draw()
            root.querySelector<HTMLInputElement>('[data-key="versions"]')?.focus()
          },
        },
    {
      label: state.system ? 'Edit system prompt' : 'Add system prompt',
      run: () => {
        openSystem()
      },
    },
  ]

  const pillItems = (state: State, name: string): Item[] => {
    const slot = state.slots.find((item) => item.name === name)
    const own = slot?.attributes.find((attribute) => attribute.name === name)
    return [
      {
        label: 'Edit values',
        run: () => {
          active = name
          draw()
        },
      },
      ...(own
        ? [
            { heading: 'Vary each value' },
            ...[...SCALES, null].map((option) => ({
              label: option ?? 'per case',
              checked: own.scale === option,
              run: () => {
                send('vary', { attribute: name, scale: option })
              },
            })),
          ]
        : []),
      { heading: '' },
      {
        label: 'Remove variable',
        run: () => {
          send('remove', { slot: name })
        },
      },
    ]
  }

  const openSystem = () => {
    system = true
    draw()
    root.querySelector<HTMLTextAreaElement>('[data-key="system"]')?.focus()
  }

  const systemLine = (state: State) => {
    if (!system)
      return h(
        'button',
        {
          type: 'button',
          class: 'msb-system',
          title: 'Edit the system prompt',
          'aria-label': 'Edit the system prompt',
          click: openSystem,
        },
        h('span', { class: 'msb-label' }, 'System'),
        state.system ? state.system.replace(/\s+/g, ' ') : h('span', { class: 'msb-muted' }, 'none'),
      )
    return h(
      'div',
      { class: 'msb-stack' },
      textArea(state.system, 'system', 'System prompt', (value) => {
        send('edit', { key: 'system', value })
      }),
      h(
        'div',
        { class: 'msb-row msb-small' },
        h('span', { class: 'msb-muted' }, 'System prompt'),
        h('span', { class: 'msb-grow' }),
        button(
          'Done',
          () => {
            system = false
            draw()
          },
          { quiet: true },
        ),
      ),
    )
  }

  const versionBar = (state: State) => {
    const versions = state.versions
    if (!versions)
      return (
        versioning &&
        h(
          'div',
          { class: 'msb-row msb-small' },
          input(
            '',
            'versions',
            'Prompt versions',
            (text) => {
              const [name = '', labels = ''] = text.split(':')
              versioning = false
              send('versions', { name: name.trim(), labels: list(labels) })
            },
            'msb-wide',
            'language: en, fr, de',
          ),
          button(
            'Cancel',
            () => {
              versioning = false
              draw()
            },
            { quiet: true },
          ),
        )
      )
    const relabel = (labels: Value[]) => {
      send('versions', { name: versions.name, labels: labels.map(String) })
    }
    return h(
      'div',
      { class: 'msb-row msb-versions' },
      input(
        versions.name,
        'versions:name',
        'Name of the prompt versions',
        (name) => {
          send('versions', { name, labels: versions.labels.map(String) })
        },
        'msb-name',
      ),
      scaleSelect(versions.scale, `Scale of ${versions.name}`, (chosen) => {
        send('vary', { attribute: versions.name, scale: chosen })
      }),
      h(
        'span',
        { class: 'msb-tabs', role: 'tablist' },
        versions.labels.map((label, index) =>
          h(
            'button',
            {
              type: 'button',
              role: 'tab',
              class: 'msb-tab',
              'aria-selected': String(index === version),
              title:
                index === 0 ? 'The baseline version' : 'Right-click to make it the baseline or remove it',
              click: () => {
                version = index
                draw()
              },
              contextmenu: (event: MouseEvent) => {
                event.preventDefault()
                const others = versions.labels.filter((_, at) => at !== index)
                menu(event.clientX, event.clientY, [
                  {
                    label: 'Make baseline',
                    run: () => {
                      version = 0
                      relabel([label, ...others])
                    },
                  },
                  {
                    label: 'Remove version',
                    run: () => {
                      relabel(others)
                    },
                  },
                ])
              },
            },
            String(label),
          ),
        ),
      ),
      input(
        '',
        'versions:add',
        'Add a version',
        (label) => {
          if (label.trim()) relabel([...versions.labels, label.trim()])
        },
        'msb-ghost msb-short',
        '+ version',
      ),
      h('span', { class: 'msb-grow' }),
      button(
        '×',
        () => {
          send('versions', { name: null, labels: [] })
        },
        { quiet: true, label: 'Remove versions', title: 'Keep only the first version' },
      ),
    )
  }

  const varies = (state: State, name: string | null) =>
    state.slots.some(
      (slot) => slot.name === name && slot.attributes.some((attribute) => attribute.scale !== null),
    )

  const pill = (state: State, piece: Piece) => {
    const name = piece.slot ?? ''
    return h(
      'span',
      {
        class: `msb-slot ${varies(state, name) ? 'msb-varied' : 'msb-fixed'}`,
        'data-slot': name,
        'aria-pressed': String(active === name),
        title: `${name}${varies(state, name) ? ', varied' : ', per case'}`,
        click: () => {
          active = active === name ? null : name
          draw()
        },
      },
      h('b', null, name),
      piece.text || h('i', null, 'empty'),
    )
  }

  const panel = (state: State) => {
    const slot = state.slots.find((item) => item.name === active)
    return slot ? card(state, slot) : null
  }

  const card = (state: State, slot: Slot) => {
    const locked = slot.shipped !== null
    const shown = String(state.prompts[version]?.label ?? '')
    const columns = ['label', slot.versioned ? `text · ${shown}` : 'text', ...slot.columns.slice(2)]
    const cells = (row: Cell[]) =>
      row.map((cell) => (typeof cell === 'object' ? (cell[shown] ?? '') : String(cell)))
    const rowOf = (values: string[], source: Cell[] = []) => {
      const [label = '', text = '', ...rest] = values
      const texts = source[1]
      const properties = slot.columns
        .slice(2)
        .map((column, index): [string, string] => [column, rest[index] ?? ''])
      return {
        label,
        text: typeof texts === 'object' ? { ...texts, [shown]: text } : text,
        ...Object.fromEntries(properties),
      }
    }
    const write = (rows: ReturnType<typeof rowOf>[]) => {
      send('rows', { slot: slot.name, rows })
    }
    const current = () =>
      [...table.querySelectorAll('tbody tr')].map((tr, index) =>
        rowOf(
          [...tr.querySelectorAll<HTMLTextAreaElement>('textarea')].map((cell) => cell.value),
          slot.rows[index],
        ),
      )
    const table = h(
      'table',
      null,
      h(
        'thead',
        null,
        h(
          'tr',
          null,
          columns.map((column, index) =>
            h(
              'th',
              null,
              column,
              !locked &&
                index > 1 &&
                button(
                  '×',
                  () => {
                    send('drop', { slot: slot.name, property: column })
                  },
                  { quiet: true, small: true, skip: true, label: `Remove property ${column}` },
                ),
            ),
          ),
          !locked &&
            h(
              'th',
              { class: 'msb-act' },
              input(
                '',
                `property:${slot.name}`,
                'Add a property',
                (property) => {
                  send('extend', { slot: slot.name, property })
                },
                'msb-ghost msb-short',
                '+ property',
              ),
            ),
        ),
      ),
      h(
        'tbody',
        null,
        slot.rows.map((row, number) =>
          h(
            'tr',
            { class: number === 0 ? 'msb-base' : null },
            cells(row).map((cell, column) =>
              h(
                'td',
                { title: number === 0 && column === 0 ? 'The baseline: the value the prompt shows' : null },
                cellArea(
                  cell,
                  locked,
                  `cell:${slot.name}:${String(number)}:${String(column)}`,
                  `${columns[column] ?? ''} ${String(number + 1)}`,
                  column === 1,
                ),
              ),
            ),
            !locked &&
              h(
                'td',
                { class: 'msb-act' },
                number > 0 &&
                  button(
                    '↑',
                    () => {
                      send('move', { slot: slot.name, row: number })
                    },
                    {
                      quiet: true,
                      small: true,
                      skip: true,
                      label: `Move value ${String(number + 1)} up`,
                      title: number === 1 ? 'Make it the baseline' : 'Move up',
                    },
                  ),
                slot.rows.length > 1 &&
                  button(
                    '×',
                    () => {
                      write(current().filter((_, index) => index !== number))
                    },
                    { quiet: true, small: true, skip: true, label: `Delete value ${String(number + 1)}` },
                  ),
              ),
          ),
        ),
      ),
    )
    if (!locked)
      table.querySelector('tbody')?.addEventListener('change', () => {
        write(current())
      })
    const own = slot.attributes.find((attribute) => attribute.name === slot.name)?.values ?? []
    const numbers = own.filter(isNumber)
    const rangeable = !locked && !slot.versioned && slot.columns.length === 2 && numbers.length === own.length
    const part = (name: string) => (name === slot.name ? 'each value' : name.slice(slot.name.length + 1))
    return h(
      'section',
      { class: `msb-card ${varies(state, slot.name) ? 'msb-varied' : 'msb-fixed'}`, 'data-slot': slot.name },
      h(
        'div',
        { class: 'msb-row' },
        input(
          slot.name,
          `name:${slot.name}`,
          'Variable name',
          (name) => {
            send('rename', { slot: slot.name, name })
          },
          'msb-name',
        ),
        locked && h('span', { class: 'msb-lib' }, `library: ${slot.shipped ?? ''}`),
        locked &&
          button(
            'Edit a copy',
            () => {
              write(slot.rows.map((row) => rowOf(cells(row))))
            },
            { quiet: true },
          ),
        h('span', { class: 'msb-divider' }),
        slot.attributes.map((attribute) =>
          h(
            'label',
            { class: 'msb-vary' },
            h('span', { class: 'msb-muted' }, part(attribute.name)),
            scaleSelect(attribute.scale, `Scale of ${attribute.name}`, (chosen) => {
              send('vary', { attribute: attribute.name, scale: chosen })
            }),
          ),
        ),
        h('span', { class: 'msb-grow' }),
        (rangeable || slot.range !== null) &&
          segmented(slot.range ? 'range' : 'list', ['list', 'range'], `Values of ${slot.name}`, (chosen) => {
            if (chosen === 'list') write(slot.rows.map((row) => rowOf(cells(row))))
            else {
              const span = spanning(numbers)
              send('range', { slot: slot.name, start: span.from, stop: span.to, step: span.step })
            }
          }),
        state.versions &&
          !locked &&
          slot.range === null &&
          h(
            'button',
            {
              type: 'button',
              class: 'msb-toggle',
              'aria-pressed': String(slot.versioned),
              title: `One text per ${state.versions.name}`,
              click: () => {
                send('per_version', { slot: slot.name, enabled: !slot.versioned })
              },
            },
            `per ${state.versions.name}`,
          ),
        button(
          'Remove',
          () => {
            send('remove', { slot: slot.name })
          },
          { quiet: true, title: 'Its first value becomes plain text again' },
        ),
        button(
          '×',
          () => {
            active = null
            draw()
          },
          { quiet: true, label: 'Close', title: 'Close (Esc)' },
        ),
      ),
      slot.attributes.map(
        (attribute) =>
          attribute.scale !== null &&
          h(
            'p',
            { class: 'msb-order' },
            h('b', null, attribute.name),
            order(attribute.scale, attribute.values),
          ),
      ),
      slot.range
        ? spanEditor(slot.name, slot.range, own, (span) => {
            send('range', { slot: slot.name, start: span.from, stop: span.to, step: span.step })
          })
        : [
            h('div', { class: 'msb-table' }, table),
            !locked &&
              button(
                '+ value',
                () => {
                  send('add', { slot: slot.name })
                },
                { quiet: true },
              ),
          ],
    )
  }

  const attributesOf = (state: State): Attribute[] => [
    ...state.slots.flatMap((slot) => slot.attributes),
    ...(state.versions
      ? [{ name: state.versions.name, scale: state.versions.scale, values: state.versions.labels }]
      : []),
  ]

  const conditions = (state: State, when: When, label: string, set: (when: When) => void) => {
    const attributes = attributesOf(state)
    const valuesOf = (attribute: string) =>
      unique(attributes.find((item) => item.name === attribute)?.values ?? [])
    return [
      when.map(([attribute, condition], at) => {
        const named = (part: string) => `${label} ${part} ${String(at + 1)}`
        const values = valuesOf(attribute)
        const numeric = values.length > 0 && values.every(isNumber)
        const change = (changed: Condition, name = attribute) => {
          set(when.map((pair, where): [string, Condition] => (where === at ? [name, changed] : pair)))
        }
        return [
          at > 0 && h('span', { class: 'msb-muted' }, 'and'),
          pick(
            named('attribute'),
            attributes.map((item) => item.name),
            attribute,
            (chosen) => {
              change(valuesOf(String(chosen))[0] ?? '', String(chosen))
            },
          ),
          numeric
            ? operatorPick(named('operator'), operatorOf(condition), (chosen) => {
                change(converted(condition, chosen, values.filter(isNumber)))
              })
            : h('span', { class: 'msb-muted' }, 'is'),
          isBound(condition)
            ? boundInputs(named, condition, change)
            : pick(named('value'), values, condition, change),
          when.length > 1 &&
            button(
              '×',
              () => {
                set(when.filter((_, where) => where !== at))
              },
              { quiet: true, small: true, label: `Remove condition ${String(at + 1)} of ${label}` },
            ),
        ]
      }),
      button(
        '+ and',
        () => {
          set([
            ...when,
            fresh(
              state,
              when.map(([key]) => key),
            ),
          ])
        },
        { quiet: true, small: true, title: 'Add a condition that must also hold' },
      ),
    ]
  }

  const fresh = (state: State, used: string[] = []): [string, Condition] => {
    const attributes = attributesOf(state)
    const free = attributes.filter((item) => !used.includes(item.name))
    const attribute = free.find((item) => item.scale !== null) ?? free[0] ?? attributes[0]
    const values = unique(attribute?.values ?? [])
    return [attribute?.name ?? '', values[1] ?? values[0] ?? '']
  }

  const answer = (state: State) => {
    const { field, pattern, choices, rules, otherwise } = state.answer
    const mode = reading ?? (pattern !== null ? 'pattern' : 'field')
    const reader = () => (mode === 'pattern' ? { field: null, pattern } : { field: field || 'answer' })
    const correct = (changed: Rule[] = rules, last: Value | null = otherwise) =>
      changed.length === 0
        ? last
        : [
            ...changed.map((rule) => ({ when: Object.fromEntries(rule.when), then: rule.then })),
            ...(last === null ? [] : [{ then: last }]),
          ]
    const commit = (changed: Rule[], last: Value | null = otherwise) => {
      send('answer', { ...reader(), choices, correct: correct(changed, last) })
    }
    const replaced = (index: number, rule: Rule | null) =>
      rules.flatMap((item, at) => (at !== index ? [item] : rule ? [rule] : []))
    const ready = Boolean(mode === 'pattern' ? pattern : field) && choices.length >= 2
    const attributes = attributesOf(state)
    const lines = rules.map((rule, index) =>
      h(
        'div',
        { class: 'msb-rule' },
        pick(`Rule ${String(index + 1)} answer`, choices, rule.then, (chosen) => {
          commit(replaced(index, { ...rule, then: chosen }))
        }),
        h('span', { class: 'msb-muted msb-word' }, 'when'),
        conditions(state, rule.when, `rule ${String(index + 1)}`, (when) => {
          commit(replaced(index, { ...rule, when }))
        }),
        h('span', { class: 'msb-grow' }),
        button(
          '×',
          () => {
            commit(replaced(index, null))
          },
          { quiet: true, small: true, label: `Remove rule ${String(index + 1)}` },
        ),
      ),
    )
    const groups = state.groups.map((group, index) =>
      h(
        'div',
        { class: 'msb-rule' },
        h('span', { class: 'msb-muted msb-word' }, 'group'),
        input(
          group.name,
          `group:${String(index)}`,
          `Name of group ${String(index + 1)}`,
          (name) => {
            if (!name || name === group.name) return
            send('group', { name: group.name, when: null })
            send('group', { name, when: Object.fromEntries(group.when) })
          },
          'msb-name',
        ),
        h('span', { class: 'msb-muted msb-word' }, 'when'),
        conditions(state, group.when, `group ${group.name}`, (when) => {
          send('group', { name: group.name, when: Object.fromEntries(when) })
        }),
        h('span', { class: 'msb-grow' }),
        button(
          '×',
          () => {
            send('group', { name: group.name, when: null })
          },
          { quiet: true, small: true, label: `Remove group ${group.name}` },
        ),
      ),
    )
    return h(
      'section',
      { class: 'msb-section msb-answer' },
      h(
        'div',
        { class: 'msb-row' },
        h('span', { class: 'msb-label' }, 'Answer'),
        segmented(mode, ['field', 'pattern'], 'Read the answer from', (chosen) => {
          reading = chosen
          if (chosen === 'field') send('answer', { field: field || 'answer', choices, correct: correct() })
          else draw()
        }),
        mode === 'field'
          ? input(
              field,
              'field',
              'Reply field',
              (value) => {
                send('answer', { field: value, choices, correct: correct() })
              },
              'msb-short',
              'decision',
            )
          : input(
              pattern ?? '',
              'pattern',
              'Reply pattern',
              (value) => {
                reading = null
                send('answer', { field: null, pattern: value, choices, correct: correct() })
              },
              'msb-short msb-code',
              '\\b(yes|no)\\b',
            ),
        h('span', { class: 'msb-muted' }, 'one of'),
        input(
          choices.join(', '),
          'choices',
          'Choices',
          (value) => {
            send('answer', { ...reader(), choices: list(value), correct: correct() })
          },
          'msb-short',
          'grant, deny',
        ),
        h('span', { class: 'msb-grow' }),
        ready &&
          mode === 'field' &&
          (state.instructed
            ? h(
                'span',
                { class: 'msb-ok msb-small', title: 'The system prompt asks for this reply' },
                '✓ asked',
              )
            : button(
                'Ask for this reply',
                () => {
                  send('instruct')
                },
                { quiet: true, title: 'End the system prompt with the reply format' },
              )),
      ),
      h(
        'div',
        { class: 'msb-rules' },
        lines,
        h(
          'div',
          { class: 'msb-rule' },
          ready
            ? pick(
                'Answer otherwise',
                choices,
                otherwise,
                (chosen) => {
                  commit(rules, chosen)
                },
                true,
              )
            : h('span', { class: 'msb-muted' }, 'Name the reply and two choices first.'),
          h('span', { class: 'msb-muted msb-word' }, rules.length > 0 ? 'otherwise' : 'always'),
        ),
        groups,
        h(
          'div',
          { class: 'msb-row msb-small' },
          button(
            '+ rule',
            () => {
              commit([
                ...rules,
                {
                  when: [fresh(state)],
                  then: choices.find((choice) => String(choice) !== String(otherwise)) ?? choices[0] ?? '',
                },
              ])
            },
            {
              quiet: true,
              disabled: !ready || attributes.length === 0,
              title: 'A different answer when attributes have certain values',
            },
          ),
          button(
            '+ group',
            () => {
              const taken = new Set(state.groups.map((group) => group.name))
              let number = state.groups.length + 1
              while (taken.has(`group${String(number)}`)) number += 1
              send('group', { name: `group${String(number)}`, when: Object.fromEntries([fresh(state)]) })
            },
            {
              quiet: true,
              disabled: attributes.length === 0,
              title: 'Cases with their own scorecard',
            },
          ),
        ),
      ),
    )
  }

  const preview = (state: State) => {
    const counts = state.counts
    const number = (key: 'cases' | 'repetitions', value: number | null, fallback: number | undefined) =>
      h(
        'label',
        { class: 'msb-field' },
        h('span', { class: 'msb-muted' }, key),
        input(
          value ?? '',
          key,
          key,
          (text) => {
            send('edit', { key, value: text ? Number(text) : null })
          },
          'msb-count',
          fallback === undefined ? '' : String(fallback),
        ),
      )
    return h(
      'section',
      { class: 'msb-section' },
      h(
        'div',
        { class: 'msb-row' },
        h(
          'span',
          { class: 'msb-muted' },
          counts
            ? `${plural(counts.variants, 'variant')}, ${plural(counts.calls, 'call')} per target`
            : 'The variants appear once the spec is complete.',
        ),
        h('span', { class: 'msb-grow' }),
        number('cases', state.cases, counts?.cases),
        number('repetitions', state.repetitions, counts?.repetitions),
      ),
      state.samples.map((sample) =>
        h(
          'div',
          { class: 'msb-sample' },
          h(
            'div',
            { class: 'msb-row msb-small' },
            h('strong', null, sample.title === 'baseline' ? 'Baseline' : sample.title),
            h('span', { class: 'msb-grow' }),
            h('span', { class: 'msb-badge' }, `correct: ${String(sample.reference)}`),
          ),
          h(
            'div',
            { class: 'msb-diff' },
            sample.parts.map(([text, kind]) => h('span', { class: `msb-${kind}` }, text)),
          ),
        ),
      ),
      counts &&
        counts.variants > state.samples.length &&
        state.samples.length > 0 &&
        h(
          'p',
          { class: 'msb-muted msb-small' },
          `Showing ${String(state.samples.length)} of ${plural(counts.variants, 'variant')}; builder.prompts lists all.`,
        ),
    )
  }

  model.on('change:state', draw)
  draw()
}

function scaleSelect(current: Scale | null, label: string, change: (scale: Scale | null) => void) {
  const element = h(
    'select',
    { 'aria-label': label },
    h('option', { value: '', selected: current === null ? true : null }, 'per case'),
    SCALES.map((option) =>
      h('option', { value: option, selected: current === option ? true : null }, option),
    ),
  )
  element.addEventListener('change', () => {
    change(SCALES.find((option) => option === element.value) ?? null)
  })
  return element
}

function order(kind: Scale, values: Value[]) {
  const [baseline = '', ...others] = unique(values).map(String)
  const text =
    kind === 'nominal'
      ? others.length > 0
        ? `${baseline} vs ${others.join(', ')}`
        : baseline
      : [baseline, ...others].join(' < ')
  return h('span', { title: ORDERS[kind] }, text)
}

function pick(
  label: string,
  values: Value[],
  current: Value | null,
  chosen: (value: Value) => void,
  empty = false,
) {
  const element = h(
    'select',
    { 'aria-label': label },
    empty && h('option', { value: '' }, 'choose…'),
    values.map((value, index) =>
      h(
        'option',
        {
          value: String(index),
          selected: current !== null && String(current) === String(value) ? true : null,
        },
        String(value),
      ),
    ),
  )
  element.addEventListener('change', () => {
    const value = values[Number(element.value)]
    if (element.value !== '' && value !== undefined) chosen(value)
  })
  return element
}

function unique(values: Value[]) {
  return values.filter(
    (value, index) => values.findIndex((other) => String(other) === String(value)) === index,
  )
}

function isNumber(value: Value): value is number {
  return typeof value === 'number'
}

function isBound(condition: Condition): condition is Bound {
  return typeof condition === 'object'
}

function operatorOf(condition: Condition): Operator {
  if (!isBound(condition)) return 'is'
  if (condition.at_least !== undefined && condition.below !== undefined) return 'between'
  return condition.at_least !== undefined ? 'at_least' : 'below'
}

function converted(condition: Condition, operator: Operator, values: number[]): Condition {
  const [first = 0] = values
  const number = isBound(condition)
    ? (condition.at_least ?? condition.below ?? first)
    : isNumber(condition)
      ? condition
      : first
  if (operator === 'is') return values.includes(number) ? number : first
  if (operator === 'at_least') return { at_least: number }
  if (operator === 'below') return { below: number }
  return { at_least: number, below: values.find((value) => value > number) ?? number + 1 }
}

function operatorPick(label: string, current: Operator, change: (operator: Operator) => void) {
  const operators = Object.keys(OPERATORS) as Operator[]
  const element = h(
    'select',
    { 'aria-label': label },
    operators.map((operator) =>
      h('option', { value: operator, selected: operator === current ? true : null }, OPERATORS[operator]),
    ),
  )
  element.addEventListener('change', () => {
    const chosen = operators.find((operator) => operator === element.value)
    if (chosen) change(chosen)
  })
  return element
}

function boundInputs(label: (part: string) => string, bound: Bound, change: (bound: Bound) => void) {
  const field = (key: keyof Bound) =>
    input(
      bound[key] ?? '',
      label(key),
      label(key === 'at_least' ? 'at least' : 'below'),
      (text) => {
        change({ ...bound, [key]: Number(text) })
      },
      'msb-count',
    )
  if (bound.at_least !== undefined && bound.below !== undefined)
    return [field('at_least'), h('span', { class: 'msb-muted' }, 'and below'), field('below')]
  return field(bound.at_least !== undefined ? 'at_least' : 'below')
}

function spanning(values: number[]): Span {
  const sorted = [...new Set(values)].sort((left, right) => left - right)
  const [low = 0] = sorted
  const high = sorted.at(-1) ?? low
  const gaps = sorted.slice(1).map((value, index) => value - (sorted[index] ?? value))
  const step = gaps.length > 0 ? Math.min(...gaps) : 1
  return { from: low, to: high > low ? high : low + step, step }
}

function spanEditor(slot: string, span: Span, values: Value[], change: (span: Span) => void) {
  const field = (key: keyof Span) =>
    h(
      'label',
      { class: 'msb-field' },
      h('span', { class: 'msb-muted' }, key),
      input(
        span[key],
        `range:${slot}:${key}`,
        `${key} of ${slot}`,
        (text) => {
          change({ ...span, [key]: Number(text) })
        },
        'msb-count',
      ),
    )
  const shown = values.length > 6 ? [...values.slice(0, 3), '…', ...values.slice(-2)] : values
  return h(
    'div',
    { class: 'msb-row msb-small' },
    field('from'),
    field('to'),
    field('step'),
    h('span', { class: 'msb-muted' }, `${plural(values.length, 'value')}: ${shown.map(String).join(', ')}`),
  )
}

function segmented<T extends string>(current: T, options: T[], label: string, change: (option: T) => void) {
  return h(
    'span',
    { class: 'msb-segmented', role: 'group', 'aria-label': label },
    options.map((option) =>
      h(
        'button',
        {
          type: 'button',
          'aria-pressed': String(option === current),
          click: () => {
            if (option !== current) change(option)
          },
        },
        option,
      ),
    ),
  )
}

function list(text: string) {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function cellArea(value: string, locked: boolean, key: string, label: string, text: boolean) {
  const area = h(
    'textarea',
    {
      class: 'msb-cell',
      rows: '1',
      readonly: locked || null,
      'data-key': key,
      'aria-label': label,
      placeholder: text ? 'empty' : '',
    },
    value,
  )
  area.addEventListener('input', () => {
    fit(area)
  })
  area.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      area.blur()
    }
  })
  return area
}

function textArea(value: string, key: string, label: string, change: (value: string) => void) {
  const area = h(
    'textarea',
    {
      class: 'msb-text',
      rows: String(Math.max(2, Math.min(10, value.split('\n').length))),
      'data-key': key,
      'aria-label': label,
    },
    value,
  )
  area.addEventListener('change', () => {
    change(area.value)
  })
  return area
}

function fit(area: HTMLTextAreaElement) {
  area.style.height = 'auto'
  if (area.scrollHeight > 0) area.style.height = `${String(area.scrollHeight)}px`
}

interface Kept {
  key: string
  value: string | null
  start: number | null
  end: number | null
}

function remembered(root: HTMLElement): Kept | null {
  const focused = document.activeElement
  if (!(focused instanceof HTMLElement) || !root.contains(focused) || !focused.dataset.key) return null
  const typed = focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement ? focused : null
  return {
    key: focused.dataset.key,
    value: typed && typed.value !== typed.defaultValue ? typed.value : null,
    start: typed?.selectionStart ?? null,
    end: typed?.selectionEnd ?? null,
  }
}

function restore(root: HTMLElement, kept: Kept | null) {
  if (!kept) return
  const next = [...root.querySelectorAll<HTMLElement>('[data-key]')].find(
    (item) => item.dataset.key === kept.key,
  )
  if (!next) return
  next.focus()
  if (!(next instanceof HTMLInputElement || next instanceof HTMLTextAreaElement)) return
  if (kept.value !== null) next.value = kept.value
  if (kept.start !== null && kept.end !== null) next.setSelectionRange(kept.start, kept.end)
}

function selected(container: HTMLElement): Caret | null {
  const selection = document.getSelection()
  const range = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  if (!range || range.collapsed || !container.contains(range.startContainer)) return null
  const piece = pieceOf(range.startContainer)
  if (!piece || piece !== pieceOf(range.endContainer)) return null
  return {
    piece: Number(piece.dataset.piece),
    start: offset(piece, range.startContainer, range.startOffset),
    end: offset(piece, range.endContainer, range.endOffset),
    text: range.toString(),
  }
}

function pieceOf(node: Node): HTMLElement | null {
  const element = node instanceof HTMLElement ? node : node.parentElement
  return element?.closest<HTMLElement>('[data-piece]') ?? null
}

export function offset(piece: HTMLElement, node: Node, at: number): number {
  const range = document.createRange()
  range.selectNodeContents(piece)
  range.setEnd(node, at)
  return range.toString().length
}

function input(
  value: string | number,
  key: string,
  label: string,
  change: (value: string) => void,
  kind = '',
  placeholder = '',
) {
  const element = h('input', {
    value: String(value),
    'aria-label': label,
    'data-key': key,
    class: kind,
    placeholder,
  })
  element.addEventListener('change', () => {
    change(element.value)
  })
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') element.blur()
  })
  if (kind === 'msb-name' || kind === 'msb-title') {
    const size = () => {
      element.size = Math.max(4, element.value.length + 1)
    }
    size()
    element.addEventListener('input', size)
  }
  return element
}

interface Look {
  primary?: boolean
  quiet?: boolean
  disabled?: boolean
  title?: string
  label?: string
  skip?: boolean
  small?: boolean
}

function button(text: string, click: () => void, look: Look = {}) {
  const kinds = [look.primary && 'msb-primary', look.quiet && 'msb-quiet', look.small && 'msb-tiny'].filter(
    Boolean,
  )
  return h(
    'button',
    {
      type: 'button',
      class: kinds.join(' ') || null,
      disabled: look.disabled === true || null,
      title: look.title ?? null,
      'aria-label': look.label ?? null,
      tabindex: look.skip ? '-1' : null,
      click,
    },
    text,
  )
}

function plural(count: number, noun: string) {
  return `${String(count)} ${noun}${count === 1 ? '' : 's'}`
}

function short(text: string, length: number) {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text
}

export default { render }
