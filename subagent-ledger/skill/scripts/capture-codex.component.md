---
type: concept
title: 'Codex capture'
description: 'Codex''s hook command. It writes both records for each subagent call, each message to a subagent and each model call made through the shell tool. It reads the model and counters from the subagent''s rollout file, Codex''s transcript.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: capture-codex
  type: handler
  lifecycle: planned
  runtime: 'a Codex hook command'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:717
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Codex capture

Codex's hook command. It writes both records for each subagent call, each message to a subagent and each model call made through the shell tool. It reads the model and counters from the subagent's rollout file, Codex's transcript.
