# The instruction a brief carries

Every member's brief carries the instruction below, so the member knows what each of the return check's four checks
looks for before it starts. Put it last in the brief's body, after the task and the write set. Copy it word for word,
and fill only its two placeholders from the settings in the ledger folder's `config.json`, under `return_check`:

- `<validator>`: the `validator` command, in backticks, such as `` `python3 /opt/tools/validate_front_matter.py` ``;
  and
- `<kinds>`: the word `Markdown`, followed in brackets by each `markdown` pattern in backticks, such as
  ``Markdown (`docs/*.md`, `notes/*.md`)``. With no `markdown` patterns set, the word `Markdown` alone.

A reworded instruction is a different contract, and the checks read only what the member did. A brief cannot be
written to this instruction with no `validator` set, since `<validator>` would stay unfilled.

The brief also carries the member key and the attempt in its front matter, and its path is the first path the prompt
names. Those are fields of the brief, not instructions to the member. The `subagent-triage` skill's
`references/brief-format.md` is their home, and says which check each one keeps from failing. The `subagent-triage`
skill writes the fields and this instruction into every brief it writes. A parent writing a brief by hand adds them
itself.

That skill's brief writer reads the instruction from this file: the first fenced block after the heading 'The
instruction'. It refuses the block unless it quotes, in backticks, the parser's heading `## Output` and its word
`none`. Keep the heading, the fences and both quotes when you change the text.

## The instruction

```markdown
## What your work is checked for

When you report, four checks read what you wrote. Each part below keeps one of them from failing.

**Write only inside your write set.** Write, edit or create files only at the paths your `## Write set` section
lists, relative to the repository's root. Your session's scratch folder is the one exception: you may write there
freely. If your write set reads `none`, write nothing outside the scratch folder. A write anywhere else, by any tool
or command, is a fault, even if you undo it.

**Give every Markdown file you write the front matter it needs.** Every <kinds> file you create or edit must pass
<validator>. Run it on each such file before you report, and fix what it names. This holds for every such file you
touch, whether or not you list it as output.

**End your report with an output section.** It lists the files you wrote as this task's output, and nothing else in
your report counts as a claim.

1. Write a line that reads exactly `## Output`, with nothing else on it.
2. Under it, write each output file's path, one a line. Give each path relative to the repository's root, as your
   write set does, or in full. You may open a line with `- ` and wrap the path in backticks.
3. If you wrote no output file, write the single word `none` on the line, and nothing else.
4. Make the section the last thing in your report. Put no heading, code fence or other text after it, and no code
   fence inside it.

A path you mention anywhere else in your report is not a claim, so name every output file in the section.

**Where the section goes.** If you hand your report back by a tool, such as `SubagentHandback` in Claude Code, put
the section at the end of the tool's `message`. Only that message is read; nothing you write after handing back is.
If you have no such tool, end your final message with the section.
```

## Which check each part keeps from failing

Each part follows a rule that has its home elsewhere: the checks in this skill's `SKILL.md`, the grammar in
`output-section.md`.

| Part of the instruction | Keeps from failing | Rule it follows |
|---|---|---|
| Write only inside your write set, or the scratch folder | check 4, writes stay in the write set | `SKILL.md`, 'The four checks' |
| Give every Markdown file its front matter | check 2, front matter conforms | `SKILL.md`, 'The four checks' |
| End with an output section, steps 1 and 2 | check 1, `fail (no output section)` | `output-section.md`, 'Where the section is' and 'What each line holds' |
| Step 3, `none` alone | check 1, `fail (output section malformed)` | `output-section.md`, 'Results' |
| Step 4, nothing after the section and no fence in it | check 1: a heading would cut the section short, and a fence would be read as paths | `output-section.md`, 'Where the section is' and 'What the grammar does not settle' |
| Name every output file in the section | check 1: a file named only in prose is not claimed | `output-section.md`, 'What each line holds' |
| Where the section goes | check 1 at a hand-back: the section must be in the message the parent receives | `output-section.md`, 'Which text is read' |

Check 3, that the call is on the ledger, asks nothing of the member. The brief's fields keep it from failing.
