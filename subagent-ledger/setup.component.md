---
type: concept
title: 'Setup'
description: 'Links the skill into each harness and prints the hook entries for you to add. It never writes a harness''s settings. It stops on a system where the ledger cannot lock its file.'
tags: [component]
generated: { by: process:okf-projectdocs }
x-component:
  name: setup
  type: interface
  lifecycle: planned
  runtime: 'command line, run by hand to install the skill'
  secrets: []
  gcs: {reads: [], writes: []}
  external-apis:
    json-schema.org:
      - https://json-schema.org/draft/2020-12/schema  # URL literal in ledger.py:620
  pubsub: {}
  depends-on: []
  overlaps-with: []
---

# Setup

Links the skill into each harness and prints the hook entries for you to add. It never writes a harness's settings. It stops on a system where the ledger cannot lock its file.
