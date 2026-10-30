---
type: concept
title: 'Brief'
description: 'Writes one member''s brief: its front matter, the opening instruction, the task, the write set and the return skill''s instruction, in that order. A path that does not resolve stops the brief.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: brief
  type: job
  lifecycle: planned
  runtime: 'command line'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:117
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Brief

Writes one member's brief: its front matter, the opening instruction, the task, the write set and the return skill's instruction, in that order. A path that does not resolve stops the brief.
