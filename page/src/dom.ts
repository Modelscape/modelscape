export type Child = Node | string | number | null | undefined | false | readonly Child[]

type Attribute = string | true | null | undefined | false | ((event: MouseEvent) => void)

export function nodes(...children: Child[]): (Node | string)[] {
  return children.flatMap((child): (Node | string)[] => {
    if (child == null || child === false) return []
    if (child instanceof Node || typeof child === 'string') return [child]
    if (typeof child === 'number') return [String(child)]
    return nodes(...child)
  })
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, Attribute> | null,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag)
  for (const [name, value] of Object.entries(attributes ?? {})) {
    if (typeof value === 'function') element.addEventListener(name, value as EventListener)
    else if (value === true) element.setAttribute(name, '')
    else if (typeof value === 'string') element.setAttribute(name, value)
  }
  element.append(...nodes(...children))
  return element
}

export function svg(tag: string, attributes: Record<string, string | number>, ...children: Child[]) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag)
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value))
  element.append(...nodes(...children))
  return element
}
