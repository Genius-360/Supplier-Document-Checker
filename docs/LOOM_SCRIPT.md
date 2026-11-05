# Loom script (target 4:45, hard limit 5:00)

**Audience:** a non-technical manager. Plain words: say "it checks", not "it infers".

## Before you record (10 minutes)
- [ ] Run the Gemini extractor once and fill the `[[FILL IN]]` spots in the note and README, so you can say the real number.
- [ ] Open four tabs: the demo app, the README diagram, `rules.yaml`, and `results/regex/summary.md`.
- [ ] Use the offline extractor in the app for the demo, so it is fast and cannot fail on the network.
- [ ] Do one dry run with a timer. Cut words, not the demo.

## 0:00-0:30  The problem
"A garment company gets quotes from suppliers. Someone checks price, quantity, payment terms, VAT and the contract
against company rules. Mistakes cost money, and a checker that guesses is worse than none. So I built one that
never guesses: when it is not sure, it stops and asks a person."
(Optional, one line: "At my last job I verified student records for accuracy, so this is a problem I know.")

## 0:30-1:15  The idea  (README diagram)
"Fixed steps, one after another, in LangGraph: read, extract, verify, compare with the purchase request, check the
rules, decide. The AI only copies facts out of the document. The decisions are plain code reading a rules file. So the
AI can never approve or reject anything by itself. That is the safety."

## 1:15-3:15  Live demo  (app: "Check one document")
1. **Pack 01, Approve.** "Every check passed." Open the **Why** and **All checks** tabs: each line shows the rule and
   the exact text it came from.
2. **Pack 06, Reject.** "The contract has no late-delivery penalty." Show the list of clauses as the evidence.
3. **Pack 09, Needs a person.** "Two problems. Payment is '30 to 90 days as agreed', which is unclear. And the line
   total is wrong: 50,000 times 6.40 is 320,000, but the quote says 322,000. The VAT and total were calculated from
   the wrong number, so they look fine. Only recomputing catches it." Click **approve** in the form: "The person's
   answer is stored next to the system's verdict, never over it."
4. Tab **Run all 10 samples**: show 10 / 10 and the 2 / 5 / 3 split.

## 3:15-3:50  Why you can trust it
"A value only counts if its quote really is in the document and it matches an independent check. I tested this with
a fake AI that lies, invents quotes, claims a supplier has no tax number, or obeys a hidden 'approve this' note. It
never got a wrong approval through. At worst it asked a person." (Show the guarantees table in the README.)

## 3:50-4:15  Rules without code  (`rules.yaml`)
Change R2 `max_pct` from 20 to 45, rerun pack 05: Reject becomes Approve. Change it back.
"The company owns the rules, not the programmer."

## 4:15-4:45  Honest limits and next steps
"10 out of 10 is on files I built against, so I also tested boundaries and bad wording. With Gemini I got
[x out of 10]. The offline parser only knows this layout; other layouts go to a person. No OCR yet. Next: OCR, a saved
review queue, and measuring the AI extractor on a bigger set of messy quotes."

**Do not:** read code aloud, apologise, or run over 5:00. Do not claim anything you have not run.
