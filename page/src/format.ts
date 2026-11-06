import type { Coordinate, Estimate, Transition } from './types'

export const number = (value: number | null | undefined) =>
  value == null ? '–' : Math.abs(value) < 0.005 ? '0.00' : value.toFixed(2)

export const magnitude = (value: number | null | undefined) =>
  value != null && Math.abs(value) >= 100 ? Math.round(value).toLocaleString('en-US') : number(value)

export const precise = (value: number) =>
  value === 0 || Math.abs(value) >= 0.01 ? number(value) : value.toPrecision(2)

export const interval = (estimate: Estimate | null, format = number) =>
  estimate == null
    ? '–'
    : estimate.lower == null || estimate.upper == null
      ? format(estimate.value)
      : `${format(estimate.value)} [${format(estimate.lower)}, ${format(estimate.upper)}]`

export const probability = (value: number | null) =>
  value == null ? '–' : value < 0.001 ? '<0.001' : value.toFixed(3)

export const count = (value: number | null) => (value == null ? '–' : value.toLocaleString())

export const moment = (value: string | null) => (value == null ? '–' : new Date(value).toLocaleString())

export const show = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value))

export const same = (first: unknown, second: unknown) => show(first ?? null) === show(second ?? null)

export const coordinate = (values: Coordinate, axes = Object.keys(values)) =>
  axes.map((axis) => `${axis}=${show(values[axis])}`).join(', ')

export const shifted = (estimate: Estimate, by: number): Estimate => ({
  value: estimate.value + by,
  lower: estimate.lower == null ? null : estimate.lower + by,
  upper: estimate.upper == null ? null : estimate.upper + by,
})

export const rate = ({ axis, start, end, excess }: Transition) => {
  const [from, to] = axis == null ? [] : [start[axis], end[axis]]
  if (typeof from !== 'number' || typeof to !== 'number' || excess == null) return null
  const step = Math.abs(to - from)
  return step === 0 || step === 1 ? null : excess.value / step
}
