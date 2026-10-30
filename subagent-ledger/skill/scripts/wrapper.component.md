---
type: concept
title: 'Wrapper'
description: 'One hook entry per event: runs the check the ledger folder names for it, then the capture, in one process. A check that errors or overruns refuses nothing; only a check''s own decision refuses a call.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: wrapper
  type: handler
  lifecycle: planned
  runtime: 'a Claude Code hook command'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:758
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Wrapper

One hook entry per event: runs the check the ledger folder names for it, then the capture, in one process. A check that errors or overruns refuses nothing; only a check's own decision refuses a call.
