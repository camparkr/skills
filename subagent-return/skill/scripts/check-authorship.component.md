---
type: concept
title: 'Authorship check'
description: 'Check 1: the files a member''s report claims in its output section are the member''s own writes. A call whose brief carries no member is not checked, and its result says why.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: check-authorship
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

# Authorship check

Check 1: the files a member's report claims in its output section are the member's own writes. A call whose brief carries no member is not checked, and its result says why.
