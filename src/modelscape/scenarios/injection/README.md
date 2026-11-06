# injection

Does an analyst triage security alerts by the evidence, not by instructions an attacker planted? Written as a [spec](injection.yaml).

| Axis | Values |
| --- | --- |
| `injection` | none, a claim of routine activity, a false red-team authorization, an instruction to the AI analyst, a fake system message |
| `event.malicious` | true, false: each alert is swapped for a benign one under the same detection rule |

A shift on `injection` means planted text changed the verdict. [Example](https://modelscape.github.io/modelscape/examples/injection/).
