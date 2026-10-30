# Decision definitions

The skill asks three questions of each part of a delegation. Each question is a decision definition, kept as one
JSON file in `skill/decisions/`:

| File | Question | Shape |
|---|---|---|
| `d1-act.json` | Which kinds of act does this part ask for? | eight Nouls, one per kind; a provisional Choice until their lines are set |
| `d3-figure.json` | Which eligible persona takes this part, and is it adequate? | exact eligibility, then a Choice, then a Noul on adequacy |
| `d4-effort.json` | Which effort level does this part warrant? | a Choice over the levels the harness offers |

A **Noul** asks whether one proposition is true and returns a probability of yes. A **Choice** picks one member of a
closed set and returns a probability for each. Neither is a measurement, and neither probability is relabelled a
score.

The three definitions are written for Jev, TypeSafe's decision engine, at model `jev-1.13.0`. Noul and Choice are
Jev's question types, and each definition's instructions and criteria are written to be asked of it. Each file names
the engine and model in its `engine` key. Asking a definition of another model, or another engine, is a change to
the definition: it takes a new version, and its lines are calibrated again.

## What a definition holds

| Key | Holds |
|---|---|
| `id` | the definition's name, the same as its file's |
| `question` | the question in one sentence |
| `definition_version` | a whole number, raised by one whenever a question, criterion, line or outcome changes |
| `provisional` | `true` while any line or criterion has no measured basis |
| `basis` | where the lines and criteria come from, in a sentence |
| `engine` | the engine and model the definition is written for and asked of: Jev, `jev-1.13.0` |
| `decision_point_classification` | `exact`, `bounded_semantic`, `mixed` or `authority_bearing` |
| `exact_facts` | the facts established exactly before any semantic question is asked |
| `composition` | each Noul and Choice with its instructions and criteria, and how their results combine |
| `outcomes` | each result the composition can reach, with the answer recorded, where the part goes and its lane |
| `override` | for a decision the parent can override: what the override records |
| `calibration` | what calibration measures, and the smallest held-out set it needs |

A line is the probability at or above which a Noul's answer counts as yes. A line set to `null` is not set yet.

## How the script asks them

`scripts/decide.py` asks the three for one part, in order, after it stamps the parent's unaided effort:

- **The act decision** asks each of its eight Nouls and records each probability. While their lines are unset it
  applies none, and the provisional Choice over the eight kinds and `none` gives the answer.
- **The persona decision** is asked only where the act decision read a kind. Eligibility is settled first, exactly.
  With no persona eligible the answer is `none adequate`, with the rule that emptied the set, and nothing is asked.
  Otherwise one Choice ranks the eligible personas, and the adequacy Noul is asked of the one it ranks first.
- **The effort decision** is asked whatever the other two read, with the kind, the persona, the task's stage and
  size measures of the part as state.

A request that fails with HTTP 429 or a 5xx status is tried again, up to three more times. Each try is a request of
its own.

## Lanes

Each outcome names one lane:

- `delivered`: the answer goes on without review, under the authority the outcome's `delegated_authority` names;
- `reasoned`: the parent weighs the answer and decides; and
- `user_ratification`: the parent raises the answer with the user, who decides.

An unchecked answer enters `delivered` only under delegated authority. A failed or timed-out request never reaches
`delivered`, and never stops a dispatch.

## The decision record

Each answer is written as a decision record into the member's pending triage file, and from there onto its dispatch
record. A record carries only these fields:

| Field | Holds |
|---|---|
| `question` | the definition's `id` |
| `definition_version` | the version applied |
| `subject` | the part asked about: its member, its attempt and the file its text came from, at the file's last commit, or at its SHA-256 where git holds none |
| `quote` | the part's text, where it is one line, so a reader can check the answer without the file |
| `answer` | one answer from the definition's outcomes, or `none` or `unrecorded` with the reason |
| `uncertainty_basis` | the probabilities returned, the line applied and its version |
| `decision_point_classification` | as the definition states it |
| `exact_evidence` | for a `mixed` definition: the exact facts supplied to the semantic question |
| `lane` | the outcome's lane |
| `delegated_authority` | where `lane` is `delivered`: who delegated it; otherwise absent |
| `evidence_state` | whether the answer has been checked against anything other than itself |
| `decided_by` | the engine and model that answered, such as Jev at `jev-1.13.0` |
| `final_disposition` | `pending`, as the script writes it |

The record's shape also has `disposed_by`, for who disposed of an answer and when, and `override`, for the override
that replaced it. The script writes neither, and leaves `final_disposition` at `pending`. An override is kept beside
the records instead, in the pending triage file's `overrides` list, each entry holding the values the definition's
`override` lists, its `decision` and the time. A persona override also restamps the file's persona and who chose it.
The records stay as the engine answered.

Beside the records, the pending triage file holds, each stamped from the clock as it is written: the parent's unaided
effort, first of all; the kind read; the persona chosen, the facts the choice rested on and who chose it; the
below-the-line mark, where it applies; any failure, with its reason; and any overrides. The ledger skill's
`pending.schema.json` defines the file.

Each request a definition makes is itself a call, with its own dispatch and return records through the ledger's
writer. The part's text goes to the engine only. No record holds it, save a one-line part as `quote`.

## Changing a definition

A definition changes only by a new version. Keep each version's results: a record names the version it was decided
under, so results from two versions are never pooled.

- **Lines** are set on a calibration half of a labelled set and tested on a held-out half. Nothing is tuned on the
  held-out half.
- **Each rate** is reported as a count of items with its exact binomial interval, beside the line it supports.
- **The best constant answer** is fixed on the calibration half, and every result is reported beside it.
- **A revision of `d4-effort.json`** is written from calibration misses only, and tested on a fresh held-out half.

A row whose line cannot be set keeps its fallback lane, and the result goes to the user.
