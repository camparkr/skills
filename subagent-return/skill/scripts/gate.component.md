---
type: concept
title: 'Gate'
description: 'While a failing return check result stands with no disposition, refuses the parent''s tool calls, save reads, a stop, a question to the user and the disposition command. A member''s tool call never meets it.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: gate
  type: handler
  lifecycle: planned
  runtime: 'run by the ledger''s wrapper at every PreToolUse of the parent'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis: {}
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Gate

While a failing return check result stands with no disposition, refuses the parent's tool calls, save reads, a stop, a question to the user and the disposition command. A member's tool call never meets it.
