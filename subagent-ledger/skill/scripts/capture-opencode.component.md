---
type: concept
title: 'OpenCode capture'
description: 'OpenCode''s capture, run by the plugin. It writes both records for each `task` call and each model call made through `bash`. When a task errors, it writes a failed return from the event stream.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: capture-opencode
  type: handler
  lifecycle: planned
  runtime: 'run by the OpenCode plugin'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:717
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# OpenCode capture

OpenCode's capture, run by the plugin. It writes both records for each `task` call and each model call made through `bash`. When a task errors, it writes a failed return from the event stream.
