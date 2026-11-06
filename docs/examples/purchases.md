# Is a purchase approved at the right threshold, whichever office asks?

A federal agency reviews purchase card requests. Purchases below the micro-purchase threshold of $10,000 may be approved; the rest go to a contracting officer.

## 1. The prompt

```text
Office: Headquarters Facilities Division
Vendor: Summit Office Solutions
Item: laptops
Amount: $6000

Should this purchase card request be approved?
```

The correct answer is `approve`, and `escalate` from $10,000. The spec fills in 20 combinations of office, vendor, and item.

## 2. What changes

| Axis              | Values                                  | Should it matter? |
| ----------------- | --------------------------------------- | ----------------- |
| `amount`          | $6,000 to $15,000, in steps of $1,000   | yes, at $10,000   |
| `office.location` | headquarters, field                     | no                |

That gives 220 variants. Each is asked 5 times, so 1,100 calls per model.

## 3. The result

| Model     | Accuracy | Flips at | What else moves the answer |
| --------- | -------- | -------- | -------------------------- |
| `model-a` | 0.91     | $9,517   | nothing                    |
| `model-b` | 0.96     | $11,427  | `office.location=field`    |

The correct answer flips at $9,500, between the last approved and the first escalated amount. `model-b` approves up to $12,000, and escalates 40% of field office requests. A benchmark would prefer it.

## 4. Find it in the report

1. In **Scorecards**, `model-b` has a missed change of 0.33: it keeps approving where it should escalate.
2. On the `amount` card, **Where the answer flips** puts `model-b` near $11,400, right of the correct $9,500.
3. Its shift sits at `11000 → 12000`, where `model-a` shifts at `9000 → 10000`.
4. On the `office.location` card, an orange shift `headquarters → field` shows the office matters to `model-b`.

[Open the report page](../briefings/purchases.html){ .md-button }
