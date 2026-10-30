---
type: concept
title: 'Return check'
description: 'Runs the four checks on a member''s report at its hand-back and its stop, and refuses nothing: each result is recorded, a fail with its repair. Its context step hands the parent the results, and its merge plan says which of a writer''s paths may come home without asking.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: return-check
  type: handler
  lifecycle: planned
  runtime: 'run by the ledger''s wrapper at a member''s hand-back and stop'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis: {}
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Return check

Runs the four checks on a member's report at its hand-back and its stop, and refuses nothing: each result is recorded, a fail with its repair. Its context step hands the parent the results, and its merge plan says which of a writer's paths may come home without asking.
