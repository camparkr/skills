# The instruction a brief carries

Every member's brief carries the instruction below, word for word, so the member ends its report with the output
section the return check reads (`output-section.md`). Put it in the brief's body, after the task and the write set.
Copy it as it stands: a reworded instruction is a different contract, and the check reads only the grammar.

The brief also carries the member key and the attempt in its front matter. Without the member key, check 1 reads
`not_applicable (no member brief)` and the section is never read. The `subagent-triage` skill writes both keys and
this instruction into every brief it writes. A parent writing a brief by hand adds them itself.

## The instruction

```markdown
## Your report's output section

End your report with an output section. It lists the files you wrote as this task's output, and nothing else in
your report counts as a claim.

1. Write a line that reads exactly `## Output`, with nothing else on it.
2. Under it, write each output file's path, one a line. Give each path relative to your working folder, or in full.
   You may open a line with `- ` and wrap the path in backticks.
3. If you wrote no output file, write the single word `none` on the line, and nothing else.
4. Make the section the last thing in your report. Put no heading, code fence or other text after it.

If you hand your report back by a tool, put the section at the end of the report you hand back. Otherwise end your
final message with it. A path you mention anywhere else in your report is not a claim, so name every output file in
the section.
```

## Why each line is there

Each line follows a rule in `output-section.md`, which is the rule's one home:

- **Line 1** follows 'Where the section is'.
- **Line 2** follows 'What each line holds', so a member's usual list style does not fail the check.
- **Line 3** follows the results table: `none` beside a path is a malformed section.
- **Line 4** follows 'Where the section is' and 'What the grammar does not settle'. A heading would cut the section
  short, and a fence would be read as paths.
- **The closing paragraph** follows 'Which text is read'.
