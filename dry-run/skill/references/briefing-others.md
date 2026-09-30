# Briefing others

Load this file only when a subagent will run the check, or when the work goes next to an outside
review.

## Where a subagent runs the check

The parent writes and commits the hypotheses first, and names that commit in the brief. The subagent
reports to the parent, which reports to the requester. The subagent runs
the check and returns the output. The parent commits the result, so the session's commits stay in order.

## Before an outside review

Before someone else tries to break the proposal, or tests the finished work against its criteria, send only
the questions no dry run could settle, with the record that shows why.

Put one of these lines in the brief. The reviewer carries it into their findings.

```
Caller's dry run: <record path> at <result commit>.
Caller's dry run: none. <Why no diff, count, test or reading could settle this question.>
```

The second line is complete only with its reason. A brief with neither line is incomplete; do not send it.
A reviewer on another machine, before the project's normal push, cannot read the record at that commit:
attach the record's text to the brief. Cite no dry run as meeting a criterion.
