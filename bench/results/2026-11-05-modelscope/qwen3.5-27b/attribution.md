# Failure attribution

19 of 25 cases passed and are excluded from the counts below; 6 failed.

| category | cases | share of failures |
|---|---|---|
| planning | 3 | 50% |
| argument_generation | 2 | 33% |
| environment | 1 | 17% |

## Cases

| case | primary | signals |
|---|---|---|
| core-01 | none | run passed |
| core-02 | none | run passed |
| core-03 | none | run passed |
| core-04 | planning | tools succeeded but the output missed constraints |
| core-05 | none | run passed |
| core-06 | none | run passed |
| core-07 | none | run passed |
| core-08 | none | run passed |
| core-09 | none | run passed |
| core-10 | none | run passed |
| core-11 | argument_generation | tool rejected its arguments |
| core-12 | argument_generation | tool rejected its arguments |
| core-13 | none | run passed |
| core-14 | none | run passed |
| core-15 | none | run passed |
| core-16 | none | run passed |
| core-17 | none | run passed |
| core-18 | none | run passed |
| core-19 | environment | host fault: RuntimeError: model endpoint unreachable: <urlopen error [SSL: UNEXPECTED_EOF_WH; ran out of steps without a final answer |
| core-20 | none | run passed |
| core-21 | none | run passed |
| core-22 | planning | tools succeeded but the output missed constraints |
| core-23 | none | run passed |
| core-24 | planning | tools succeeded but the output missed constraints |
| core-25 | none | run passed |

## 3 cases in detail

### core-04 — planning
- (planning) tools succeeded but the output missed constraints

### core-11 — argument_generation
- (argument_generation) tool rejected its arguments

### core-12 — argument_generation
- (argument_generation) tool rejected its arguments


> Rules over trace signals, not a model. `unclassified` means the taxonomy has no rule for it yet, which is information, not a gap to hide.
