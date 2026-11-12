---
type: concept
title: 'Decide'
description: 'Asks Jev the act, form, persona, harness, model and effort decisions for one part, records each request on the ledger, and writes the part''s pending triage file, except for a part read as none or sent back to be split. Its override mode records a persona, level, harness or model the parent passes instead, or a dispatch sent with no persona.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: decide
  type: job
  lifecycle: planned
  runtime: 'command line'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:171
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Decide

Asks Jev the act, form, persona, harness, model and effort decisions for one part, records each request on the ledger, and writes the part's pending triage file, except for a part read as none or sent back to be split. Its override mode records a persona, level, harness or model the parent passes instead, or a dispatch sent with no persona.
