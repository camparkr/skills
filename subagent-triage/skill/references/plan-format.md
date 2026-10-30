# The plan file

The plan file says how a delegation is divided into a team. It is written before the first dispatch, beside the
briefs, and the skill's `close` reads it last. It is an input to the calls, not their record. The ledger's dispatch
and return records are the record.

So the plan holds no value that belongs on a record and nowhere else. It never holds an effort, a decision's
probability, an override or a check result. Those go into the member's pending triage file, and from there onto its
dispatch record.

## Fields

The plan file is JSON, so the scripts and `close` read it exactly. `scripts/plan.py write` writes it from the
proposal the parent approved ('The proposal' below), and never over a file that already stands.

| Key | Holds |
|---|---|
| `plan_request` | the plan's id, unique within the session. The planner's own dispatch names it. Without one, the script makes one |
| `task` | the task's id |
| `written_at` | when the plan was first written, from the clock |
| `pattern` | the set of act kinds the plan's parts carry, sorted by name |
| `members` | one entry per member and attempt, as below |
| `parallel` | the order the members run in: a list of groups, each group a list of member ids that run together. Each member appears once |
| `synthesiser` | `parent`, or the member id of the member that writes the synthesis |
| `hops` | each hand-over between a member and the parent, as below |
| `changes` | each change the parent made to the planner's proposal, and each hop left out or restored, as below |
| `closed_at` | when `close` ran; absent until then |

Each **member** entry holds:

| Key | Holds |
|---|---|
| `member` | the member's id |
| `attempt` | `1`, or the attempt number of a re-dispatch |
| `part` | what the part asks for, in a sentence |
| `act_kind` | the kind the act decision read |
| `persona` | the persona the brief names |
| `brief` | the brief's absolute path. The brief must already exist |
| `repository` | the repository the write set lies in, or `none` for a read-only member |
| `write_set` | the write set's paths, each relative to the repository's root, or `none` |
| `redispatch_reason` | for an attempt after the first: why the parent sent it again |

A re-dispatch is a new entry under the same member id, with the next attempt number. It never replaces the earlier
entry. `scripts/plan.py redispatch` adds it to a plan not yet closed: it copies the member's last entry, raises the
attempt by one, and sets the new brief, the reason and, where given, a new persona.

Each **hop** holds:

| Key | Holds |
|---|---|
| `from` | the member id whose output is handed over |
| `to` | `parent`, or the member id that receives it |
| `kind` | `return` for a member's report to the parent, or `synthesis` for the synthesiser's |
| `cited` | `null` until `close`; then `true` or `false` |
| `citation` | where `cited` is `true`: what the parent's output named or quoted. `close` writes it |

Each **change** holds four keys, each as text: `part`, the part it changes; `proposed`, what the planner proposed;
`chosen`, what the parent chose; and `reason`, why.

## The proposal

`plan.py write` reads the approved proposal from a JSON file. It holds `task`, `members`, `parallel` and
`synthesiser`, and may hold `plan_request`, `hops`, `changes` and `restore`. It holds no other key, and each member
entry holds only the member keys above. A value that belongs on a record, such as an effort, has no place in it.

- **Members** carry `attempt` where it is not 1. Each member's attempts run 1, 2 and so on, and each after the first
  gives its `redispatch_reason`. Each `act_kind` is one of the ledger's kinds.
- **Hops** may be left out. Then each member's return to the parent is a hop: `synthesis` for the synthesiser's, and
  `return` for the rest. A hop given in the proposal holds `from`, `to` and `kind` only.
- **`restore`** names each hop the parent keeps although the last closed plan of this pattern marked it not cited
  ('The next plan' below). Each entry holds `from`, `to`, `kind` and `reason`. A restore naming a hop that would not
  be left out is refused.

The script refuses the proposal, writing nothing, where a rule above is broken, a brief is not an existing file by
absolute path, or the parallel order does not hold each member once.

## The planner's own pending file

Where a planner runs, `plan.py planner` writes its pending file before it is dispatched:
`<ledger>/.pending/<session>/planner-<plan request>.json`, holding the plan request id and the time. The ledger's
capture reads no value from it: its name is the evidence. Where the planner's brief carries no member key and names
that plan request id, standing alone, the capture records the dispatch as the planner's own, naming the plan request,
and removes the file. Give the same id to `plan.py write`, so the plan names it too.

## Example

```json
{
  "plan_request": "plan-3",
  "task": "2026-01-15-report-refresh",
  "written_at": "2026-01-15T03:12:40Z",
  "pattern": ["build", "verdict-or-review"],
  "members": [
    {"member": "m1", "attempt": 1, "part": "Rebuild the report's tables from the new data.", "act_kind": "build",
     "persona": "builder", "brief": "/work/briefs/m1-1.md", "repository": "report", "write_set": ["tables/"]},
    {"member": "m2", "attempt": 1, "part": "Review the rebuilt tables against the data standard.",
     "act_kind": "verdict-or-review", "persona": "reviewer", "brief": "/work/briefs/m2-1.md",
     "repository": "none", "write_set": "none"}
  ],
  "parallel": [["m1"], ["m2"]],
  "synthesiser": "parent",
  "hops": [
    {"from": "m1", "to": "parent", "kind": "return", "cited": null},
    {"from": "m2", "to": "parent", "kind": "return", "cited": null}
  ],
  "changes": [
    {"part": "m2", "proposed": "a separate synthesiser", "chosen": "parent", "reason": "two short reports"}
  ]
}
```

## Closing the plan

The parent runs `close`, `scripts/close.py`, when the team's work is done. For each hop, `close` reads the parent's
transcript and marks the hop cited or not cited. It writes each hop's `cited` and `citation`, and `closed_at`, into
the plan file, and refuses a plan already closed.

**The return it reads.** The hop's member's return is that of its last attempt that returned. Its returned text is
the ledger's copy of the return's answer, and its output paths are the lines of that text's output section. A hop
whose member never returned is not cited.

**The output it reads.** The parent's first output after the hop's return. Where the hop ran in a parallel group, it
is the first output after the group's last return. An output is one of:

- a reply: a text block the parent writes;
- a file the parent writes, by Write, Edit, MultiEdit or NotebookEdit: its path and its new text; or
- the prompt of its next dispatch, by Agent or Task.

**Cited** means that output does one of these:

- names one of the hop's output paths, or its call id, standing alone and not inside a longer name; or
- carries a run of at least 20 consecutive words of the hop's returned text, word for word. A word is a run of
  letters, digits and underscores, with any apostrophe inside it.

Reading the hop's output is not a citation. Nor is acting on it in the parent's own words. The 20 words are a
starting value, not yet measured. The report gives each hop the output it was judged by, so a miss can be seen.

**The next plan.** When `plan.py write` writes a plan, it looks for the most recent closed plan, by `closed_at`, with
the same `pattern`, among the plan files under its history folders: the new plan's own folder unless others are
named. It matches each hop that plan marked not cited by the hop's kind and the act kinds of its two ends, and leaves
out each matching hop of the new plan, unless the proposal's `restore` names it. Each hop left out, and each one
restored, is recorded as a change, with its reason.

`close` also reports:

- each pending triage file and planner's file whose dispatch never happened. It removes none of them;
- the plan's entries and how many were dispatched, the entries not dispatched and each dispatch the plan does not
  list: the planner's, members' own, refused ones, those with no persona and any other. Resumptions are left out of
  every count;
- the count of parts dispatched below the persona decision's line, and which parts they were, with each probability,
  line and line version;
- the override rates, each as a count of overrides out of the dispatches decided, never a percentage: the persona
  decision's overall, by its adequacy band in tenths from 0.0 to 1.0 and by parent; and the effort decision's
  overall. The parent is the persona `close` is given, or else the parent's own persona the overrides name, where
  they name exactly one; and
- each fault: a dispatch the plan does not list, an override missing a value it records, an effort passed other than
  the one to pass and an unaided effort stamped after the decisions.

The effort to pass is the last effort override's level, else the effort decision's level, else, where it gave none,
the parent's unaided level. `close` exits 0 when it closed with no fault, and 3 when it closed with faults.
