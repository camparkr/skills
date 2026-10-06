# Compose, validate and render the report

## Compose the review record

Read [`../references/questions/score.md`](../references/questions/score.md) in full, for the score and the report's
order. Run `python3 <skill>/scripts/report.py schema` and compose the record it describes, copying each persona's
branches from `find.py`. Give each persona a fit entry, because every report carries one. For each nearby file, ask
three questions:

- Does it claim the same request as this persona?
- Does it give a rule that conflicts with one of this persona's?
- Does it set a condition this persona's own answers ignore?

Quote the line from each file for every yes. When every answer is no, say that nothing was found.

## Validate the record

Pass the record on standard input, so it never touches the disk. Write each `<` in it as `\u003c` and each `>` as
`\u003e`, because some harnesses refuse those characters in a shell command; the scripts read them back as written:

```bash
python3 <skill>/scripts/report.py validate - <<'RECORD'
{ ...the record... }
RECORD
```

When it refuses the record, read [`../references/sample-review.md`](../references/sample-review.md), which shows a sound
review, then fix each fault it lists and run it again until it exits 0, at most three reruns. Past that the fault is in
the review, not the record: stop.

## Render the report

Run `python3 <skill>/scripts/report.py render - <<'RECORD'` with the validated record, and add `--summary` before the
`-` when there is more than one persona. Return the report it prints.

On exit 2, when `render` refuses the record, fix each fault it lists and render again, at most three renders after the
first; then stop, as for `validate`. On exit 3, no persona got a total because each was empty, set aside or had no
question apply: stop, because there is no score to report.

