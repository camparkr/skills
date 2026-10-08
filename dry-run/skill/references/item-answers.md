# Item answers

Where a dry run answers one question about every item it touches, such as each file in a rename, it
records one answer per item. The answers sit inside the session's dry-run record, under the dry run that
made them.

A question's id, version and closed set of answers come from the project's standard for it. With none,
write them into the dry run's hypotheses, as version 1, before answering.

**The usual form: many items, one question.** Write one table per dry run with the columns `subject` and
`answer`, adding `home` for a placement question. A header above it states the shared fields once:
`question`, `definition_version` and `decided_by`.

**A single answer** carries `question`, `definition_version`, `subject`, `answer` and `decided_by`.
The rest are conditional, as each row says.

Use these field names, so answers from different dry runs can be compared. Where a question is a series of
tests, keep only the final answer, not each test's result.

| Field | Meaning |
|---|---|
| `question` | the id of the question asked, such as `placement` |
| `definition_version` | the version of that question's definition applied |
| `subject` | what was asked about, cited at the version read: `<path>@<commit>:<line>` for a line, `<path>@<commit>` for a whole file, or a record |
| `quote` | where the subject is one line: its text, so a reader can check the answer without the file |
| `answer` | one answer from the question's closed set, or `none` with the reason; report each `none`. For a placement question, the rule or kind that decides the move; two subjects can share an answer and have different homes |
| `home` | for a placement question only: where the answer sends the subject |
| `decided_by` | who answered: the agent and session, or the person |
