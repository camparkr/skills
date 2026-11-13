---
type: concept
title: 'Stage'
description: 'Reads a task''s stage from named files only: a build specification, a ratified specification, or unrecorded with the reason. Proposals, findings, test criteria and amendments never count. It writes nothing.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: stage
  type: engine
  lifecycle: planned
  runtime: 'command line, and imported by decide.py'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    api.typesafe.ai:
      - https://api.typesafe.ai/v1/systemone  # URL literal in decide.py:117
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Stage

Reads a task's stage from named files only: a build specification, a ratified specification, or unrecorded with the reason. Proposals, findings, test criteria and amendments never count. It writes nothing.
