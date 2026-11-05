# Results (regex extractor)

**Verdict correct: 10 of 10.** Verdict and exact set of failed rules both correct: 10 of 10.

**Confusion matrix** (rows = hand-labelled answer, columns = system verdict)

| expected \ system | Approve | Reject | Needs a person |
|---|---|---|---|
| Approve | 2 | 0 | 0 |
| Reject | 0 | 5 | 0 |
| Needs a person to check | 0 | 0 | 3 |

| Pack | Item | System verdict | Expected | Failed rules | Why |
|---|---|---|---|---|---|
| supplier-pack-01 | A | Approve | Approve OK | - | All 13 checks passed (R1, R2, R3, R4, R5, N1, N2, N3, N4, N5, N6, N7, P1). |
| supplier-pack-02 | B | Approve | Approve OK | - | All 13 checks passed (R1, R2, R3, R4, R5, N1, N2, N3, N4, N5, N6, N7, P1). |
| supplier-pack-03 | C | Reject | Reject OK | R1 | R1: Unit price 229 is 9.05% above the maximum 210. |
| supplier-pack-04 | D | Needs a person to check | Needs a person to check OK | N1 | N1: Unit price 6.65 is 2.31% above the maximum 6.5. |
| supplier-pack-05 | E | Reject | Reject OK | R2 | R2: Advance payment is 40%, above the 20% limit. |
| supplier-pack-06 | A | Reject | Reject OK | R3 | R3: There is no late-delivery penalty clause. |
| supplier-pack-07 | B | Needs a person to check | Needs a person to check OK | N2 | N2: Quoted quantity 16,500 differs from the requested 20,000 by -17.50% (limit 5%). |
| supplier-pack-08 | C | Reject | Reject OK | R4 | R4: Supplier TIN and BIN not shown. |
| supplier-pack-09 | D | Needs a person to check | Needs a person to check OK | N3, N6 | N3: Payment terms are unclear: a range of 30 to 90 days instead of a fixed period. |
| supplier-pack-10 | E | Reject | Reject OK | N5, R5 | R5: Delivery is promised in 60 days (more than 45 days). |
