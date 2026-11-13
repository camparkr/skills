# Decision definitions

The skill asks up to six questions of each part of a delegation. Each question is a decision definition, kept as
one JSON file in `skill/decisions/`:

| File | Question | Shape |
|---|---|---|
| `d1-act.json` | Which kinds of act does this part ask for? | nine Nouls, one per kind; a provisional Choice until their lines are set |
| `d3-figure.json` | Which eligible persona takes this part, and is it adequate? | exact eligibility, then the forms map's builder or a Choice, then a Noul on adequacy |
| `d4-effort.json` | Which effort level does this part warrant? | a Choice over the levels the assigned harness offers the assigned model |
| `d5-form.json` | Does code or a model's inference decide the output of what this part builds? | a Choice over code, model, both and none, for a build part only |
| `d6-harness.json` | Which reachable harness fits this part best? | a Choice over the harnesses the reachable list names |
| `d7-model.json` | Which reachable model fits this part best? | a Choice over the models the reachable list gives the assigned harness |

A **Noul** asks whether one proposition is true and returns a probability of yes. A **Choice** picks one member of a
closed set and returns a probability for each. Neither is a measurement, and neither probability is relabelled a
score.

The six definitions are written for Jev, TypeSafe's decision engine, at model `jev-1.13.0`. Noul and Choice are
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
| `asked_for_kind` | for a decision asked of one kind only: that kind |
| `builders` | for the form decision: where the builder for each form is named, and what happens when none is |
| `composition` | each Noul and Choice with its instructions and criteria, and how their results combine |
| `outcomes` | each result the composition can reach, with the answer recorded, where the part goes and its lane |
| `override` | for a decision the parent can override: what the override records |
| `calibration` | what calibration measures, and the smallest held-out set it needs |

A line is the probability at or above which a Noul's answer counts as yes, or the form decision's answer stands. A
line set to `null` is not set yet.

## How the script asks them

`scripts/decide.py` asks them for one part, in order, after it stamps the parent's unaided effort:

- **The act decision** asks each of its nine Nouls and records each probability. While their lines are unset it
  applies none, and the provisional Choice over the nine kinds, `none` and `two-or-more` gives the answer. A part
  read as `none` goes back to the parent as a finding. A part read as `two-or-more` goes back to be split into one
  part per kind, each triaged on its own. Neither gets a persona or a pending file.
- **The form decision** is asked only of a part read as `build`: whether code or a model's inference decides the
  output of what it builds, both, or neither. `code` or `model` names the builder through the forms map the settings
  give. `both` sends the part back to be split, one part for each form. `none` means the part builds no capability,
  and the persona Choice decides. An answer below the line of 0.5 goes to the builder the map names for `model`, and
  the record marks it below the line, with its probability, the line and its version.
- **The persona decision** is asked only where the act decision read one kind and nothing split the part.
  Eligibility is settled first, exactly. A `verdict-or-review` part also loses every persona in the group of the
  persona that did the work it calls to account, read from that work's own dispatch record; where no record names
  that persona, no persona is chosen and the part goes back as a finding. Where the form decision named a builder,
  that builder is the answer if it is eligible, and nothing is asked; a map with no eligible builder sends the part
  back as a finding. With no persona eligible the answer is `none adequate`, with the rule that emptied the set, and
  nothing is asked. Otherwise one Choice ranks the eligible personas by each one's declared goal and what it declares
  it does, with the part, its kind and the task's stage as state. The adequacy Noul is asked of the persona it ranks
  first. No decision reads who sent the part.
- **The harness decision** and then **the model decision** are asked whatever the others read. The harness comes
  from the reachable list the settings give, and the model from the models that list gives the assigned harness.
  With one listed, it is assigned without asking. With none listed, or a request that fails or answers off the
  list, the parent's own is passed and the record says why.
- **The effort decision** is asked last, whatever the others read, over the levels the assigned harness offers the
  assigned model. Its state is the kind, the persona, the task's stage, size measures of the part, and the harness
  and model assigned. Where the model is offered no level the decision defines, or the request fails, the parent's
  unaided level is passed.

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

The record's shape also has `disposed_by`, for who disposed of an answer and when, and `override`, for the override that
replaced it. The script writes neither, and leaves `final_disposition` at `pending`. An override is kept beside the
records instead, in the pending triage file's `overrides` list, each entry holding the values the definition's
`override` lists, its `decision` and the time. A persona override also restamps the file's persona and who chose it, and
a harness override restamps the harness to pass. A harness or model override off the reachable list is refused, as is an
effort level the assigned harness does not offer the assigned model. The records stay as the engine answered.

Beside the records, the pending triage file holds, each stamped from the clock as it is written: the parent's unaided
effort, first of all; the kind read; the persona chosen, the facts the choice rested on and who chose it; the
below-the-line mark, where it applies; the harness to pass (`harness_assigned`); who sent the part (`sender`), or
`unrecorded (<reason>)`, which no decision reads; any failure, with its reason; and any overrides. No pending file is
written for a part read as `none` or sent back to be split. The ledger skill's `pending.schema.json` defines the file.

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
