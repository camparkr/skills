# The plan file

The plan file says how a delegation is divided into a team. It is written before the first dispatch, beside the
briefs, and the skill's `close` reads it last. It is an input to the calls, not their record. The ledger's dispatch
and return records are the record.

So the plan holds no value that belongs on a record and nowhere else. It never holds an effort, a decision's
probability, an override or a check result. Those go into the member's pending triage file, and from there onto its
dispatch record.

## Fields

The plan file is JSON, so the scripts and `close` read it exactly.

| Key | Holds |
|---|---|
| `plan_request` | the plan's id, unique within the session. The planner's own dispatch names it |
| `task` | the task's id |
| `written_at` | when the plan was first written, from the clock |
| `pattern` | the set of act kinds the plan's parts carry, sorted by name |
| `members` | one entry per member and attempt, as below |
| `parallel` | the order the members run in: a list of groups, each group a list of member ids that run together |
| `synthesiser` | `parent`, or the member id of the member that writes the synthesis |
| `hops` | each hand-over between a member and the parent, as below |
| `changes` | each change the parent made to the planner's proposal, as below |
| `closed_at` | when `close` ran; absent until then |

Each **member** entry holds:

| Key | Holds |
|---|---|
| `member` | the member's id |
| `attempt` | `1`, or the attempt number of a re-dispatch |
| `part` | what the part asks for, in a sentence |
| `act_kind` | the kind the act decision read |
| `persona` | the persona the brief names |
| `brief` | the brief's absolute path |
| `repository` | the repository the write set lies in, or `none` |
| `write_set` | the write set's paths, or `none` |
| `redispatch_reason` | for an attempt after the first: why the parent sent it again |

A re-dispatch is a new entry under the same member id, with the next attempt number. It never replaces the earlier
entry.

Each **hop** holds:

| Key | Holds |
|---|---|
| `from` | the member id whose output is handed over |
| `to` | `parent`, or the member id that receives it |
| `kind` | `return` for a member's report to the parent, or `synthesis` for the synthesiser's |
| `cited` | `null` until `close`; then `true` or `false` |
| `citation` | where `cited` is `true`: what the parent's output named or quoted |

Each **change** holds the part it changes, what the planner proposed, what the parent chose and why.

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

The parent runs `close` when the team's work is done. For each hop, `close` reads the parent's transcript and marks
the hop cited or not cited.

**The output it reads.** The parent's first output after the hop's return. Where the hop ran in a parallel group, it
is the first output after the group's last return. An output is a file the parent writes, the prompt of its next
dispatch, or its reply.

**Cited** means that output does one of these:

- names the hop's output path or its call id; or
- carries a run of at least 20 consecutive words of the hop's returned text, word for word.

Reading the hop's output is not a citation. Nor is acting on it in the parent's own words. The 20 words are a
starting value, not yet measured.

**The next plan.** When the skill writes a plan, it finds the most recent closed plan with the same `pattern`. It
leaves out each hop that plan marked not cited, unless the parent restores it. A restored hop is a change, with its
reason.

`close` also reports:

- each pending triage file whose dispatch never happened. It removes none of them;
- each dispatch whose member id the plan does not list;
- the count of parts dispatched below the persona decision's line, and which parts they were; and
- the override rate, as a count of overrides out of dispatches, by the persona decision's probability band and by
  parent.
