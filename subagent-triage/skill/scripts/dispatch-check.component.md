---
type: concept
title: 'Dispatch check'
description: 'Refuses a dispatch that no triage reached, with the reason. It lets through a dispatch whose pending file exists, records a failed triage or records a dispatch with no persona, the planner''s own dispatch and a member''s own. It writes nothing.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: dispatch-check
  type: handler
  lifecycle: planned
  runtime: 'run by the ledger''s wrapper at PreToolUse on Agent and Task'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:117
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Dispatch check

Refuses a dispatch that no triage reached, with the reason. It lets through a dispatch whose pending file exists, records a failed triage or records a dispatch with no persona, the planner's own dispatch and a member's own. It writes nothing.
