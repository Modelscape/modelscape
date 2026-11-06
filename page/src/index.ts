import { render } from './page'
import { review } from './review'
import styles from './styles.css'
import type { Data, Review } from './types'

const host = document.currentScript?.previousElementSibling
const data = host?.querySelector('script[type="application/json"]')?.textContent
if (host instanceof HTMLElement && data) {
  const style = document.createElement('style')
  style.textContent = styles
  const root = document.createElement('div')
  root.classList.toggle('ms-page', host.parentElement === document.body)
  host.attachShadow({ mode: 'open' }).append(style, root)
  const parsed = JSON.parse(data) as Data | { scenario: Review }
  if ('scenario' in parsed) review(root, parsed.scenario)
  else render(root, parsed)
}
