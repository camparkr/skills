# Evidence

This file summarises the record kept while *persona-judge* was built, which the skill's sources cite as RE1. The record
itself is not published; this summary gives what it found, how, and where it falls short, so a reader can weigh the
claims that rest on it.

## How the evidence was gathered

One persona file, an agent that challenges proposals and rates each flaw on a named severity scale, was tested against
two rewrites of it: a stripped draft that moved most of its rules to other files, and a lighter draft. Each test was a
dry run with its hypotheses written down and committed before any run:

- the same task was run three times on each version, on two harnesses, Claude Code and Codex;
- a scorer who did not know which version wrote an output scored each one, and a second blind scorer judged the
  versions against each other in pairs;
- every check had a control: a planted fault, or a deliberately weakened output, that the check had to catch, so a
  check that could not fail proved nothing; and
- afterwards, `skill-judge` scored the three versions, for comparison with the blind judgements.

## What it found

1. **A total score did not separate two versions that blind judges did.** `skill-judge` scored the current file 72
   and the stripped draft 71, out of 120. In the blind pairs, the current file was judged the better challenge in
   every pair run on Claude Code. This is why the report leads with the quoted lines and says that a score does not
   predict behaviour.
2. **A scale named without its meanings drifts.** The stripped draft named the severity scale but dropped what each
   level means, and on Claude Code it rated a major flaw as fatal in two runs; the current file, which gives the
   meanings, did not. This grounds 'Terms defined where they are used'.
3. **A file nothing points to is not read.** An index that no loaded text pointed to was opened in none of six runs.
   With a pointer to a standard, Claude Code opened that standard in three runs of three; without one, in none of
   three. This grounds 'Pointers carry their triggers'. One result cuts the other way: a bare path, with no word on
   when to open it, did as well as a pointer that said when.
4. **The reviews named the causes the runs found.** Unprompted, `skill-judge`'s findings on the three versions named
   the undefined scale (finding 2) and a rule to ask a question that a delegated agent may have no one to answer.

## Where it falls short

- Three runs to each cell, on one persona and its rewrites: enough to show a difference, too few to measure how often
  each mistake happens. No rule in the review claims to know that.
- Codex stopped early in many runs, so several results rest on Claude Code alone.
- Whether an agent asks when nobody can answer was not observed: neither version asked in any run, so that test was
  inconclusive.
- The blind pair judgements were made by a model, not by people.
