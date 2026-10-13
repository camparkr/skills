---
type: concept
title: 'Calls'
description: 'Reads the ledger. It lists every call joined from its two records and every absence with its reason. Given the transcripts, it also checks that no call was missed. It writes nothing and calls no model.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: calls
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

# Calls

Reads the ledger. It lists every call joined from its two records and every absence with its reason. Given the transcripts, it also checks that no call was missed. It writes nothing and calls no model.
