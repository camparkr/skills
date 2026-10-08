# Checks that read a model's output

Load this file only when the check reads what a model does under instructions, such as a persona, a role
file or a prompt. That is the instructions row of the decision table in `SKILL.md`.

*Drawn from dry runs of one persona file on several harnesses, 6 to 8 October 2026. A harness is the program
that runs a model, such as a command-line agent. The evidence covers one file and one family of proposals,
written by one author. 'What rests on what', at the end, says which rules rest on facts about those runs and
which on judgement.*

## What a good one looks like

**The counter-example.** A dry run gave a persona several versions of its file. It asked each one 'In one
sentence, what is your job on this proposal?' and 'Who besides you should look at this proposal?'. Every
version but the inverted one gave its file's answer. The answers showed what the model said about itself.
Each question's wording also invited its own answer: 'who besides you' drew lists of other people. The task
asked for one sentence, but the file set a findings format, and over half the answers kept the file's
format. The control changed one line of the file and was never caught.

**The better design.** The next dry run handed the persona the work: 'This proposal has been sent to you.
Reply in no more than N words.' The task names no act, so the check could observe whether the model
challenged the proposal, and how. The proposal carried planted flaws, one of them where the file is silent.
Closed questions read each reply. The control inverted the whole file: its title, goal, remit, directives
and output format. The reading caught the inverted file's ruling in every scout reply. The scouts then showed
every in-role version writing the same review, with each measure at a ceiling or a floor. So the dry run
stopped before a main run that could have shown no difference. A scout that stops a run has done its job.
Its word cap proved too tight for the file's own format, as item 3 below records.

## Asking

These rules shape the task and the reading:

1. **Observe the work; never ask the model about itself.** A self-report echoes its instructions.
2. **Name no act in the task.** 'For your challenge' names it; 'This proposal has been sent to you. Reply in
   no more than N words.' leaves it to the model.
3. **Never contradict the instructions under test.** Constrain only what they leave open, such as length. A
   model breaks a word cap its instructions' own format cannot fit. One model kept its file's format and ran
   past the cap, even when told longer replies are discarded. Measure length; do not assume it.
4. **Give each measure room to move.** A plant every version finds, or an option no reply picks, cannot show
   a difference. The most conspicuous flaw, often a number, takes first place in every reply. In the scout,
   no option should hold more than about 70% of the in-role replies.
5. **Make the control invert the instructions as a whole.** Show in the scout that the reading tells it
   apart.
6. **Read with closed questions.** Check length and format with code (below).
7. **Scout on real output before writing the hypotheses** (below).
8. **Isolate each harness, prove it from what the runs did and watch the runs as they come in** (below).

## The scout

Before writing the hypotheses, run each version of the instructions a few times on the real task. Read every
output in full. The scouts behind this file ran each version a few times; that size was a design choice, not
a measured minimum. Use the scout to fix the task, the plants and the questions. Its outputs are never
findings and never evidence; say so in the record.

Test every classifier question on the scout's outputs, not on answers you wrote. Written replies separated
cleanly, where the first real ones exposed several questions. Some scored alike replies far apart. Others read
a structural finding as a process one, or a structural verdict as a decision.

## Reading with a classifier

Some tools sort a reply by returning a choice, a score or a yes-or-no, each with its confidence. Such a tool
reads short replies quickly and the same way every time. It judges what a reply does; it cannot produce the
reply.

| Returns | Use it for | Example |
|---|---|---|
| a choice among named options, one of them 'Other' | what a reply mainly does, or which issue it raises first | 'What does this reply mainly do with the proposal?': Tests what the design rests on / Reviews how it will be carried out / Decides whether it should go ahead / Rewrites or improves it / Acknowledges, summarises or asks / Other |
| a score on described levels | a matter of degree | 'How much of this reply concerns the rollout plan: the pilot, who runs it, staff training or the order in which cafés change over?': None of it / A passing mention / About a quarter of it / About half of it / Most or all of it |
| yes or no | one plant, or one behaviour | 'Does the reply say that leave approved after the Sunday rota is built is missed, or never reaches the rota?' |

These practices make the reading hold:

- **Word each question from real replies.** The first wording of the yes-or-no above was 'Does the reply
  point out that leave is read only once a week, so leave approved after that read is missing from the
  week's rota?'. It scored replies saying the same thing anywhere from near no to near yes. The reworded
  question said yes to every one.
- **Define each option where a reply could fall between two.** A closing verdict on the proposal's structure
  first read as deciding. The option then said 'A verdict on the structure alone is not this'.
- **Count softly.** Sum each option's probability over the replies, so a half-and-half reply counts half to
  each. Between two versions on one harness, soft counts showed a change that top-choice counts hid.
- **Route by confidence.** In one sample, a second sorter agreed with nearly every reply the classifier sorted
  with high confidence. It agreed with fewer than half of those sorted with low confidence. One routing drawn
  from that sample: take replies at 0.95 confidence or above as sorted. Send a random tenth of those from 0.80
  to 0.95, and every reply under 0.80, to a second sorter. That sorter sees neither the version nor the first
  reading. No run has tested these bands; set your own from a sample of your own.
- **Report the low-confidence share for each version.** A fall in confidence can itself be a result.
- **Check length and format with code, not the classifier.** A pattern match read the format right on every
  scout reply. The classifier gave middling scores to replies plainly in the format.

## Isolation and watching the runs

These keep each harness apart and its results sound:

- **Prove isolation from what each harness's runs touched:** its session records, the files it opened and
  the folder it worked in. A listing of installed skills, or a working-folder setting, proved nothing. One
  harness's installed skills put the project's own terms into most of its answers. Another took its project
  from the shell's `PWD`, not the folder it was started in, and read project files in most runs. A check for
  project names in the answers could not see a read that left no name.
- **Run each harness from a scratch home** with no skills, extensions or user rules. Run it in an empty folder
  outside the project, with `PWD` set to that folder.
- **Watch the runs as they come in.** Usage caps, rate limits and expired sign-ins failed without stopping the
  runs. Most of one harness's runs returned a usage-limit message, and their empty answers were scored. An
  expired sign-in voided a batch of answers on another. A third retried a rate limit until each run timed out.
  Count only answers with text from runs that finished. Rerun or leave out the rest, and report how many for
  each harness.
- **Report every result per harness.** The harness varied more than any version tested. On one question, one
  harness almost never named an issue that another named in most of its answers.

## What rests on what

**Facts about these runs**, within the limits at the top of this file:

- isolation fails unless proven from what the runs did;
- the instructions as a whole govern the work, and one contrary line does not;
- the instructions' own format outranks the task's request;
- the harness varies more than any version tested; and
- written answers flatter a classifier's questions.

**Judgement:**

- the room-to-move test, from a few scouts on one harness;
- the scout's size;
- the confidence bands, from one sample;
- naming no act in the task; and
- the size of difference a dry run counts as an effect.
