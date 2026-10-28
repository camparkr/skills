# The output section

A member ends its report with an output section. The section lists the files the member claims as its output, and
nothing else in the report is a claim. Check 1 reads the section and nothing else. This file states the grammar the
parser applies. The parser is `skill/scripts/output_section.py`; where it and this file differ, one of them is wrong,
and the difference is reported.

## Which text is read

The parser reads the text the parent receives, and never the member's closing text:

- **At a hand-back**, the text is that call's `message`, the report the member hands back by its hand-back tool.
- **At a stop after a delivered hand-back**, the text is the delivered `message`. The stop's own last message is
  closing text, and is not read.
- **At a stop with no delivered hand-back**, the text is the member's final message.

Closing text is never a claim, whatever it holds. A section in closing text after a delivered hand-back is not read.

## Where the section is

The section is the text after the last line of the report that reads exactly `## Output`, up to the next line that
begins with `#`, or to the end of the report.

- *Exactly* means the line holds those nine characters and nothing else once its line ending is removed. A line
  reading `## Output:`, `## Outputs`, `### Output` or `## Output ` (with a trailing space) does not open a section.
- *The last line* means a report holding two such lines has its section after the second. The first is ordinary text.
- *A line that begins with `#`* ends the section, whatever follows the `#`. A line indented before its `#` does not.

## What each line holds

Each non-blank line in the section is one claim. A line is blank when it holds only spaces or tabs. A claim is
one of:

- **one path**, absolute or relative to the member's working root. A writer's working root is its worktree. A
  read-only member's is the main checkout. The path may be wrapped in one pair of backticks, and the line may open
  with `- ` or `* `. The parser removes the marker, then the backticks, then the spaces around what is left; or
- **the single word `none`**, in lower case, with the same optional marker and backticks. `None` or `NONE` is read
  as a path.

A path named anywhere else in the report, as evidence or for any other reason, is not a claim. No semantic question
is asked of the report.

## Results

Check 1 applies only to a call whose brief carries the member key (see `brief-instruction.md`). Any other call was
never told to write the section, so its check 1 reads `not_applicable (no member brief)`. Such calls include the
planner's own dispatch and a dispatch whose first file is not a brief.

For a call whose brief carries the member key:

| The section | Check 1 |
|---|---|
| reads `none` and nothing else | `not_applicable` |
| is missing: no line reads exactly `## Output` | `fail (no output section)` |
| has no non-blank line | `fail (output section malformed)` |
| holds `none` beside a path | `fail (output section malformed)` |
| lists one or more paths | each path is judged as a claimed file; check 1 passes only when every one is the member's |

A claimed file is the member's when all of these hold:

- it exists;
- it changed after the dispatch time of this member's attempt; and
- for a writer, its worktree's changes against the baseline include it, committed or not, however it was written.

A read-only member owns no output file, so a read-only member that claims one fails check 1. The baseline and the
dispatch time sit on the member's dispatch record.

## Examples

Each example is the end of a report the parent receives from a member whose brief carries the member key.

**A claim, read only from the section.** The prose names `report.md` and the section lists it. `report.md` is
claimed once, from the section. The prose's mention is not a claim.

```text
I checked `report.md` against the standard and found two gaps.

## Output
- `report.md`
```

**No output file.** A read-only reviewer cites its inputs in prose and claims nothing. Check 1 reads
`not_applicable`.

```text
The brief's three inputs (`a.md`, `b.md`, `c.md`) agree.

## Output
none
```

**Two headings.** The section is the text after the second `## Output`. `draft.md` is not claimed.

```text
## Output
draft.md

Revised after review.

## Output
final.md
```

**The section ends at the next heading.** `notes.md` is claimed. `appendix.md` sits under `## Appendix` and is not.

```text
## Output
notes.md
## Appendix
appendix.md
```

**Fails.**

| Report ends with | Check 1 |
|---|---|
| `## Outputs` then `a.md` | `fail (no output section)`: the heading is not exact |
| `## Output` and nothing after it | `fail (output section malformed)` |
| `## Output` then `none` then `a.md` | `fail (output section malformed)` |
| `## Output` then `missing.md`, a file that does not exist | `fail`, naming `missing.md` |
| `## Output` then a file the member did not change | `fail`, naming the file |

**Closing text after a hand-back.** A member hands back a report ending `## Output` then `a.md`, which it wrote. Its
closing text then ends `## Output` then `none`. Check 1 reads the hand-back's message and passes. The closing text
is not read.

## What the grammar does not settle

- A code fence inside the section is not special. Its fence lines are read as paths, and each fails as a file that
  does not exist. Members are told to write no fence in the section.
- A path holding spaces is read whole, as written. A path that needs quoting in a shell needs none here.
