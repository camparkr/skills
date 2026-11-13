#!/usr/bin/env python3
"""Check 1: the files a member's report claims as its output are the member's own.

The claims are the lines of the report's output section (output_section.py), and nothing else in the report. The
report is the text the parent receives, which call_context.py reads. The check applies only to a call whose brief
carries the member key: any other call was never told to write the section, so its result is
`not_applicable (no member brief)`. A hand-back member's stop with no delivered hand-back before it carries no report:
`not_applicable (no report at this stop)`.

  * No output section: `fail (no output section)`. No non-blank line, or `none` beside a path:
    `fail (output section malformed)`. `none` alone: `not_applicable`.
  * A claimed file is the member's when it exists, it changed after the dispatch time of this member's attempt, and,
    for a writer, its worktree's changes against the baseline include it, committed or not. A read-only member owns
    no output file, so its claim fails. A relative path is read against the member's working root: its worktree for
    a writer, the working folder for a read-only member.
  * With no dispatch record for this member and attempt there is no dispatch time or baseline to read against:
    `not_checkable (no dispatch record ...)`. A worktree git cannot read against its baseline is `not_checkable`.

Each `fail` carries a recommended repair, written from what the check found. No model is asked anything.
"""

import os

import call_context as cc
import output_section

CHECK, NAME = 1, 'authorship'


def fail(reason, paths, repair):
    return cc.result(CHECK, NAME, cc.FAIL, reason=reason, paths=paths, repair=repair)


def run(call):
    if not call.member_brief:
        return cc.result(CHECK, NAME, cc.NOT_APPLICABLE, reason='no member brief')
    if not call.report_applies:
        return cc.result(CHECK, NAME, cc.NOT_APPLICABLE, reason='no report at this stop')
    if call.report_text is None:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=call.report_problem or 'no report text')
    section = output_section.parse(call.report_text)
    if section.state == output_section.MISSING:
        return fail('no output section', [], 'Ask the member, at a new attempt, to end its report with a line '
                    'reading exactly `## Output` and its output files under it, or `none`. Or read the report '
                    'yourself and treat it as claiming nothing.')
    if section.state == output_section.MALFORMED:
        return fail('output section malformed', [], 'The output section has %s. Ask the member, at a new attempt, '
                    'to list one path a line, or the single word `none` alone. Or read the report yourself and treat '
                    'it as claiming nothing.' % section.reason)
    if section.state == output_section.NONE_STATE:
        return cc.result(CHECK, NAME, cc.NOT_APPLICABLE)
    claims = section.claims
    if call.dispatch is None:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='no dispatch record for this member and attempt: no '
                         'dispatch time or baseline to read against')
    if not call.writer:
        return fail('a read-only member claims output', claims, 'The member was read-only and claims %s. Credit none '
                    'of them to it: look for each file, and read check 4\'s result for where it wrote.'
                    % ', '.join(claims))
    since = call.dispatched_at()
    if since is None:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason='the dispatch record carries no readable dispatch time')
    changed, problem = call.changes()
    if problem:
        return cc.result(CHECK, NAME, cc.NOT_CHECKABLE, reason=problem)
    missing, stale, unchanged = [], [], []
    for claim in claims:
        path = cc.canonical(claim, call.root)
        if not os.path.exists(path):
            missing.append(claim)
        elif os.path.getmtime(path) <= since.timestamp():
            stale.append(claim)
        elif path not in changed:
            unchanged.append(claim)
    if not (missing or stale or unchanged):
        return cc.result(CHECK, NAME, cc.PASS)
    reasons, repairs = [], []
    if missing:
        reasons.append('claimed file does not exist: %s' % ', '.join(missing))
        repairs.append('Do not act on the claim to %s: no such file exists. Ask the member, at a new attempt, to '
                       'write it or take it out of its output section.' % ', '.join(missing))
    if stale:
        reasons.append('claimed file not changed since the dispatch: %s' % ', '.join(stale))
        repairs.append('Do not credit the member with %s: it has not changed since the dispatch at %s. Check it is '
                       'not a stale copy before you use it.' % (', '.join(stale), call.dispatch.get('dispatched_at')))
    if unchanged:
        commit, _problem = call.baseline()
        reasons.append("claimed file not among the worktree's changes: %s" % ', '.join(unchanged))
        repairs.append("Do not credit the member with %s: its worktree's changes against the baseline %s do not "
                       "include it." % (', '.join(unchanged), (commit or '')[:12]))
    return fail('; '.join(reasons), missing + stale + unchanged, ' '.join(repairs))
