# Supplier Document Checker: one-page note

BIAI AI Engineer Round 2, Task 1 · Shishir Majumder

**What I built**
A fixed LangGraph pipeline that checks each supplier quotation and answers **Approve**, **Reject** or **Needs a person
to check**, quoting the exact text behind the answer. Steps: read the PDF, extract facts, verify them against the text,
compare with the purchase request, apply the company rules, decide, and pause for a person when unsure. The AI only
copies facts into a schema. All judgement is plain code reading `rules.yaml`, so an AI mistake cannot silently become a
decision.

**How I tested it**
I labelled all 10 packs from `company-rules.md`, then wrote 88 automated tests: the 10 samples; exact boundaries (20%
advance, 45 days, 5% quantity, 3% price, 30-day validity); one-change edits of a clean pack; unclear wording (must go
to a person); and a fake model that invents quotes, gives real-but-wrong numbers, falsely claims "no TIN", obeys a
hidden instruction, returns broken JSON or goes offline. In every case the result was the right verdict or "Needs a
person", never a silent Approve or a false Reject.

**Results**

| | Verdict correct | Verdict + exact failed rules |
|---|---|---|
| Offline rule-based parser | 10 / 10 | 10 / 10 |
| Gemini + cross-check | 10 / 10 | 10 / 10 |

Split: 2 Approve, 5 Reject, 3 Needs a person. The offline run takes about one second. The hardest packs: **09** (line total is wrong, but VAT and total were calculated from the wrong
figure, so only recomputing quantity x price catches it), **10** (VAT-included price; the Reject comes from 60-day
delivery) and **08** (TIN and BIN missing, worded "available on request").

**What does not work well**
- 10/10 is on files I built against. It shows these documents work, not that every layout will.
- The offline parser knows only this layout; others become "unknown" and go to a person (safe, but not automated).
- No OCR, so scanned PDFs go to a person. One line item per document.
- The rules are silent on some cases, so I chose: a weak or unmeasurable penalty goes to a person; a VAT-included
  price is judged on both VAT bases. The README lists every such decision.
- A paused review lives in memory and is lost on restart.

**What I would do next**
Add OCR; keep paused reviews in SQLite; build a larger set of messy quotes and measure the AI extractor's automation
rate and error rate separately; feed reviewers' corrections back into the rules; support Bangla supplier documents.

**AI tools used.** Claude, for planning, code, tests and documentation.
