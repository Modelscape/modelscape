# conditioning

Does the answer to a fact depend on the language it is asked in, on sensitive topics only? Written as a [spec](conditioning.yaml).

Eight sensitive multiple-choice questions, such as the year of the Tiananmen Square crackdown, each paired with a control about the same country. Scorecards are reported for `all`, `sensitive`, and `control`.

| Axis | Values |
| --- | --- |
| `language` | en, zh, ru, fr: versions of the whole prompt, with each question and requester translated |
| `requester` | none, student, journalist, government official |

A shift on sensitive questions that controls don't show is conditioning on the topic. The translations still need review by native speakers.
