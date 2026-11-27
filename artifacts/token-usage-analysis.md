# Part 2 token usage

Measured from `django__django-15368-trajectory.json` and `django__django-15368-baseline-trajectory.json` using provider-reported usage.

| Metric | Compacted | Full context |
| --- | ---: | ---: |
| Model reported by provider | deepseek-flash | deepseek-flash |
| ReAct steps | 30 | 17 |
| Compaction requests | 6 | 0 |
| ReAct input tokens | 127,877 | 141,395 |
| Mean input tokens per ReAct step | 4,263 | 8,317 |
| Peak ReAct input tokens | 5,824 | 13,719 |
| ReAct output tokens | 5,187 | 2,582 |
| Compaction input tokens | 30,244 | 0 |
| Compaction output tokens | 3,472 | 0 |
| Total tokens including compaction | 166,780 | 143,977 |

## Active context at compaction

| After ReAct step | Estimated before | Estimated after | Reduction |
| ---: | ---: | ---: | ---: |
| 9 | 6,297 | 1,939 | 69.2% |
| 13 | 6,135 | 2,073 | 66.2% |
| 14 | 5,951 | 4,897 | 17.7% |
| 16 | 5,674 | 1,628 | 71.3% |
| 21 | 5,897 | 1,892 | 67.9% |
| 23 | 5,221 | 1,575 | 69.8% |

## Observations

Mean ReAct input was 4,054 tokens lower with compaction.
Overall usage including summaries was 22,803 tokens higher with compaction.

Summaries can reduce repeated input and discard details from older tool output. They also cost a separate model request. The total depends on the size of those requests and how many ReAct steps each stochastic run takes.
