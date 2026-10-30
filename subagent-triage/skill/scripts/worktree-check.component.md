---
type: concept
title: 'Worktree check'
description: 'Refuses a writer''s dispatch whose worktree would not hold its write set as the main checkout has it, or whose write set spans two repositories, with the reason. It writes nothing.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: worktree-check
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

# Worktree check

Refuses a writer's dispatch whose worktree would not hold its write set as the main checkout has it, or whose write set spans two repositories, with the reason. It writes nothing.
