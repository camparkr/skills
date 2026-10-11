---
type: concept
title: 'Commands'
description: 'Splits a shell command into the parts the shell runs, so a model call inside a longer command is found.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: commands
  type: engine
  lifecycle: planned
  runtime: 'imported by the Claude Code capture'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:613
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Commands

Splits a shell command into the parts the shell runs, so a model call inside a longer command is found.
