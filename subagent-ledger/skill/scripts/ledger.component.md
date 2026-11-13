---
type: concept
title: 'Ledger'
description: 'The one writer: every line in the ledger goes through it. It checks each line against the schema and removes anything that looks like a secret. Then it keeps the brief and the answer as files, with a fingerprint of each, and appends the line under a lock. The lock works on macOS, Linux and Windows.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: ledger
  type: engine
  lifecycle: planned
  runtime: 'imported by the captures, the call scripts and the reader'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:717
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Ledger

The one writer: every line in the ledger goes through it. It checks each line against the schema and removes anything that looks like a secret. Then it keeps the brief and the answer as files, with a fingerprint of each, and appends the line under a lock. The lock works on macOS, Linux and Windows.
