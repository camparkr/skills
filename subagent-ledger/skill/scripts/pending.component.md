---
type: concept
title: 'Pending'
description: 'Reads the pending file a planning skill leaves for one dispatch, copies its stamped values onto the dispatch record and removes it, never outside the session''s pending folder. Also joins a resumption to the dispatch it continues.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: pending
  type: engine
  lifecycle: planned
  runtime: 'imported by the Claude Code capture'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:739
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Pending

Reads the pending file a planning skill leaves for one dispatch, copies its stamped values onto the dispatch record and removes it, never outside the session's pending folder. Also joins a resumption to the dispatch it continues.
