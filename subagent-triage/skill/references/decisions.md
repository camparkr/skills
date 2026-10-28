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
score. The shapes follow the typed-decision service the skill calls. The definitions name no provider, so another
service with the same shapes can answer them.

## What a definition holds

| Key | Holds |
|---|---|
| `id` | the definition's name, the same as its file's |
| `question` | the question in one sentence |
| `definition_version` | a whole number, raised by one whenever a question, criterion, line or outcome changes |
| `provisional` | `true` while any line or criterion has no measured basis |
| `basis` | where the lines and criteria come from, in a sentence |
| `decision_point_classification` | `exact`, `bounded_semantic`, `mixed` or `authority_bearing` |
| `exact_facts` | the facts established exactly before any semantic question is asked |
| `composition` | each Noul and Choice, its instructions and criteria, and how their results combine |
| `outcomes` | each result the composition can reach, with the answer recorded, where the part goes and its lane |
| `override` | for a decision the parent can override: what the override records |
| `calibration` | what calibration measures, and the smallest held-out set it needs |

A line is the probability at or above which a Noul's answer counts as yes. A line set to `null` is not set yet.

## Lanes

Each outcome names one lane:

- `delivered`: the answer goes on without review, under the authority the outcome's `delegated_authority` names;
- `reasoned`: the parent weighs the answer and decides; and
- `user_ratification`: the parent raises the answer with the user, who decides.

An unchecked answer enters `delivered` only under delegated authority. A failed or timed-out request never reaches
`delivered`, and never stops a dispatch.

## The decision record

Each answer is written as a decision record into the member's pending triage file, and from there onto its dispatch
record. A record carries these fields and no others:

| Field | Holds |
|---|---|
| `question` | the definition's `id` |
| `definition_version` | the version applied |
| `subject` | the part asked about: its member, attempt and plan |
| `answer` | one answer from the definition's outcomes, or `none` or `unrecorded` with the reason |
| `uncertainty_basis` | the probabilities returned, the line applied and its version |
| `decision_point_classification` | as the definition states it |
| `exact_evidence` | for a `mixed` definition: the exact facts supplied to the semantic question |
| `lane` | the outcome's lane |
| `delegated_authority` | where `lane` is `delivered`: who delegated it; otherwise absent |
| `evidence_state` | whether the answer has been checked against anything other than itself |
| `decided_by` | the service and model version that answered |
| `final_disposition` | `pending`, `accepted` or `overridden`: what the parent did with the answer |
| `disposed_by` | who disposed of it, and when; absent while `pending` |
| `override` | where `overridden`: the override's fields, as the definition's `override` lists them |

Each request a definition makes is itself a call, with its own dispatch and return records through the ledger's
writer.

## Changing a definition

A definition changes only by a new version. Keep each version's results: a record names the version it was decided
under, so results from two versions are never pooled.

- **Lines** are set on a calibration half of a labelled set and tested on a held-out half. Nothing is tuned on the
  held-out half.
- **Each rate** is reported as a count of items with its exact binomial interval, beside the line it supports.
- **The best constant answer** is fixed on the calibration half, and every result is reported beside it.
- **A revision of `d4-effort.json`** is written from calibration misses only, and tested on a fresh held-out half.

A row whose line cannot be set keeps its fallback lane, and the result goes to the user.
