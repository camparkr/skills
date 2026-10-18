---
type: concept
title: 'Claude Code capture'
description: 'Claude Code''s hook command. It writes both records for each subagent call, each message to a running subagent and each model call made through the command line. It reads the model and counters from the call''s own transcript.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: capture-claude-code
  type: handler
  lifecycle: planned
  runtime: 'a Claude Code hook command'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:717
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Claude Code capture

Claude Code's hook command. It writes both records for each subagent call, each message to a running subagent and each model call made through the command line. It reads the model and counters from the call's own transcript.
