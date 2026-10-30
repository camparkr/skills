---
type: concept
title: 'Close'
description: 'Closes a plan. It marks each hop cited or not cited from the parent''s transcript, and reports the plan''s dispatches, the parts below the line, the override rates, the pending files never dispatched and each fault. It removes nothing.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: close
  type: job
  lifecycle: planned
  runtime: 'command line'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:110
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Close

Closes a plan. It marks each hop cited or not cited from the parent's transcript, and reports the plan's dispatches, the parts below the line, the override rates, the pending files never dispatched and each fault. It removes nothing.
