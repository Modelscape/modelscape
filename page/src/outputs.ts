import type { Behind, Output, Outputs } from './types'

export function resolve(outputs: Outputs, behind: Behind): Output[] {
  return behind.flatMap(([index, score]) => {
    const observation = outputs.observations[index]
    const variant = observation && outputs.variants[observation.variant]
    return observation && variant ? [{ ...observation, ...variant, score }] : []
  })
}
