# Example dry runs

*Recorded examples from the building of this skill, 27 to 29 September 2026.*

## Restructure, rename, migration

**Control found.** A skill folder was to land with none of its source project's internal names in it. The
dry run counted those names across its files, then ran the same count on a scratch copy with one name
planted. The count found the plant, so the clean result of zero could be trusted.

**Thirteen-file rename.** Thirteen files were to be renamed. The dry run built two scratch worktrees, one as
it stood and one with only the renames. It ran the same checks in each and compared the rows. Its control
was weak: the checks were run twice on the untouched tree. One hypothesis was refuted: no single file
pattern in the tool's access rules could cover the renamed files without catching their neighbours. The
folder layout was changed before the build to fix this. One check script also lost coverage of those files
without any error, so the build counted its rows before and after. With a rerun as its control, its
supported findings were inconclusive; the refuted one stood.

## Code change that alters or adds behaviour

A loader was to stop converting timestamps. The dry run tried the changed loader on ten cases, and all ten
were right. As the control, the stock loader ran on the same ten cases and failed them as expected. That
showed the remedy right in principle only. The build used different code, and an independent run of it found
three inputs it mishandled.

## Code change that alters no behaviour, such as a refactor

The copy script's `remove` asked in two places whether a path was a registered copy; the
refactor moved that question into one function. A suite of seven cases ran on the old and the new script
and gave identical output. As the control, a copy of the new code with one planted fault, the function
checking the wrong path, changed the result: a base copy was left behind and still registered. The
control was caught, so the identical output could be trusted.

## Redraft

This skill's steps for making and removing copies were reworded, with three hypotheses
about what a reader would do: how many sentences to plant, what to do with a stray file after a check, and
how to make the scratch copies. The hypotheses were committed first. Two fresh subagents each read one copy
without knowing which: the clean redraft, and one with planted sentences for the first two hypotheses. The
planted copy's reader followed both plants ('One planted sentence'; 'Delete it quietly'), so the reading
was shown able to fail; the clean copy's reader answered as intended. The third hypothesis had no plant,
so its finding was inconclusive, not supported: it was first recorded as supported and corrected. A
one-sentence redraft needs one hypothesis and one planted sentence, still read blind: a reader who
knows which copy is planted tests nothing.

## Design, decision, specification

A ruling would add a column to a table in the project's standards. The dry run added it to a copy with a
script and parsed the table: fifteen rows, seven cells each. A search found every reader of the file and
showed that no code parsed it. The cost it surfaced, an edit needing ratification plus two sentences in
another file, went to the requester as cost. Its control was weak: no case that should fail was run, so
under the decision table its finding was inconclusive.