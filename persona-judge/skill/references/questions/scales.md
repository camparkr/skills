# Review questions

The questions *persona-judge* asks of a persona file and the formula that turns the answers into a score are in the
files of this folder, each read at the step of `reviewer.md` that uses it. This file holds the scales. Each source is
cited by its key; `sources.md`, at the plugin's root beside this skill, gives its full reference and the date it was
read.

A persona is a dedicated agent: a named specialist with its own instructions, and often its own tools and context,
such as a subagent or a custom agent. It holds instruction, which the model reads and nothing enforces, and it may
hold bound parts: settings the harness applies (the tools the agent may use, its permission mode) and code the file
names to run. A persona can be spread over several files, and the review covers all of them.

## Checks and ratings

Some questions have one right answer that a script or a careful reading settles. Others are judged across every
place in the file they apply to.

**Checks** are met or not. A check is met when nothing in the file contradicts it, and scores its weight, shown as
'yes 1', or 'yes 3' for the three weighted checks; it is not met when anything does, shown as 'no 0'. Checks marked
*script* run in `check.py` from a table, without a model, and give the same answer on every run. Checks marked
*reading* are answered by the reviewer, who quotes the line behind every 0.

**Ratings** are judged on a seven-point scale chosen for the answer the question seeks (SC1). Two are used.

### Frequency scale

*How many places meet the question.* The reviewer lists every place the question applies, quotes each one, counts how
many meet it and rates the share:

| Point | Word | Share of places that meet the question |
|---|---|---|
| 6 | always | all |
| 5 | almost always | over 80%, below 100% |
| 4 | usually | over 60%, up to 80% |
| 3 | about half the time | 40% to 60% |
| 2 | seldom | 20%, below 40% |
| 1 | almost never | more than none, below 20% |
| 0 | never | none |

The report quotes only the places that fall short; the places that meet the question count toward its point and
stay in the review record.

### Quality scale

*How well the file does something.* The reviewer rates on Brown's seven-point quality scale against the anchors the
question states for each point and quotes the lines behind the rating:

| Point | Word |
|---|---|
| 6 | exceptional |
| 5 | excellent |
| 4 | very good |
| 3 | good |
| 2 | fair |
| 1 | poor |
| 0 | very poor |
