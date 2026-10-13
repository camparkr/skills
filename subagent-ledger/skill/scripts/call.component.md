---
type: concept
title: 'Call'
description: 'Makes one call to Gemini CLI or Cursor in a fresh folder, prints the answer and writes both records.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: call
  type: interface
  lifecycle: planned
  runtime: 'command line'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:620
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Call

Makes one call to Gemini CLI or Cursor in a fresh folder, prints the answer and writes both records.
