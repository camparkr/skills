# Briefing others

Load this file only for a fresh reader's brief, a subagent that runs the check or an outside review that
comes next.

## Briefing a fresh reader

A fresh reader may run on any harness. With no subagents, a new session given only the brief counts. Brief
each reader the same way:

- Ask what the text tells an agent to do in each situation a hypothesis covers, never the hypothesis itself.
- Say nothing of plants or of a second copy.
- For a design, decision or specification, give the should-fail case as one more case in the brief. Do not
  label it, or reveal the hypothesis.
- Record the brief word for word in the hypotheses commit.

A brief that has worked: 'Read only <path>. Read no other file. <The situation.> What does the text tell you
to do? Quote the line you rely on, or say that no line covers it. Change nothing and run nothing.'

## Where a subagent runs the check

The parent writes and commits the hypotheses first, and names that commit in the brief. The subagent runs
the check and returns the output to the parent, which reports to the requester. The parent commits the
result, so the session's commits stay in order.

## Before an outside review

Before someone else tries to break the proposal or tests the finished work, send only the questions no dry
run could settle. Send with them the record that shows why.

Put one of these lines in the brief. The reviewer carries it into their findings.

```
Caller's dry run: <record path> at <result commit>.
Caller's dry run: none. <Why no diff, count, test or reading could settle this question.>
```

The second line is complete only with its reason. A brief with neither line is incomplete; do not send it.
A reviewer on another machine, before the project's normal push, cannot read the record at that commit:
attach the record's text to the brief. Cite no dry run as meeting a criterion.
