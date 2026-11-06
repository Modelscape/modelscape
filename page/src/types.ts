export type Value = string | number | boolean | null
export type Coordinate = Record<string, Value>

export interface Estimate {
  value: number
  lower: number | null
  upper: number | null
}

interface CaseTransition {
  case: string
  between: number | null
  within: number | null
  excess: number | null
}

export interface Transition {
  target: string
  versus: string | null
  axis: string | null
  start: Coordinate
  end: Coordinate
  between: Estimate | null
  within: Estimate | null
  excess: Estimate | null
  p_value: number | null
  observations: number
  per_case: CaseTransition[]
  outputs: Behind
}

export interface Candidate {
  transition: Transition
  adjusted_p_value: number
  rationale: string
}

export interface MetricPoint {
  target: string
  coordinate: Coordinate
  estimate: Estimate
  observations: number
  per_case: { case: string; value: number }[]
  outputs: Behind
}

export interface Threshold {
  reference: number
  offset: Estimate | null
  width: Estimate | null
}

export interface AxisScore {
  axis: string
  scale: 'nominal' | 'ordinal' | 'numeric'
  role: 'invariant' | 'causal'
  accuracy: MetricPoint[]
  shifts: Candidate[]
  threshold?: Threshold | null
}

export interface Scorecard {
  target: string
  group: string
  cases: string[]
  accuracy: Estimate
  answered: number | null
  spurious_change: number | null
  missed_change: number | null
  axes: AxisScore[]
}

export interface Divergence {
  first: string
  second: string
  contrasts: Transition[]
  candidates: Candidate[]
}

export interface TargetProvenance {
  identity: { name: string; version: string; parameters: Record<string, unknown> }
  models: string[]
  observations: number
  failed: number
  input_tokens: number | null
  output_tokens: number | null
  cost: number | null
}

export interface Provenance {
  modelscape: string
  python: string
  platform: string
  created_at: string
  first_observation: string | null
  last_observation: string | null
  targets: TargetProvenance[]
}

export interface Report {
  scenario: { name: string; version: string }
  experiment: string
  scorecards: Scorecard[]
  divergences: Divergence[]
  provenance: Provenance
}

export interface Prompt {
  system: string | null
  messages: { role: string; content: string }[]
}

export type Behind = [number, number | null][]

export interface Observation {
  target: string
  repetition: number
  text: string
  error: string | null
  variant: number
}

export interface Variant {
  case: string
  coordinate: Coordinate
  prompt: Prompt
  reference: unknown
}

export type Output = Omit<Observation, 'variant'> & Variant & { score: number | null }

export interface Outputs {
  observations: Observation[]
  variants: Variant[]
}

export interface Data {
  report: Report
  outputs: Outputs | null
}

export type Selection =
  | { kind: 'transition'; title: string; candidate: Candidate }
  | { kind: 'point'; title: string; point: MetricPoint }

export type Inspect = (selection: Selection) => void

export type Part = [string, 'same' | 'added' | 'removed']

export interface ReviewAxis {
  name: string
  scale: AxisScore['scale']
  role: AxisScore['role']
  values: Value[]
  baseline: Value
}

export interface ReviewVariant {
  changed: [string, Value][]
  reference: unknown
  parts: Part[]
  system?: string | null
}

export interface ReviewCase {
  case: string
  reference: unknown
  variants: ReviewVariant[]
}

export interface Review {
  name: string
  version: string
  description: string
  repetitions: number
  system: string | null
  axes: ReviewAxis[]
  cases: ReviewCase[]
}
