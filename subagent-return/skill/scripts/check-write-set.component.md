---
type: concept
title: 'Write set check'
description: 'Check 4: the member''s writes stay inside its write set, read from the worktree''s changes and from the transcript''s file tools, each path compared in canonical form.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: check-write-set
  type: engine
  lifecycle: planned
  runtime: 'imported by the return check'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis: {}
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Write set check

Check 4: the member's writes stay inside its write set, read from the worktree's changes and from the transcript's file tools, each path compared in canonical form.
