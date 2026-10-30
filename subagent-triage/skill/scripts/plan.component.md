---
type: concept
title: 'Plan'
description: 'Writes the plan file before the first dispatch, lists a re-dispatch against its member, and writes the planner''s own pending file. A hop the last closed plan of the same pattern marked not cited is left out.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: plan
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

# Plan

Writes the plan file before the first dispatch, lists a re-dispatch against its member, and writes the planner's own pending file. A hop the last closed plan of the same pattern marked not cited is left out.
