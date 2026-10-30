---
type: concept
title: 'Witness'
description: 'Checks the ledger is writing for this session before a team''s first dispatch, by finding the session-start witness line in the session''s own ledger file. With none, the skill stops and says why.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: witness
  type: job
  lifecycle: planned
  runtime: 'command line'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:110
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Witness

Checks the ledger is writing for this session before a team's first dispatch, by finding the session-start witness line in the session's own ledger file. With none, the skill stops and says why.
