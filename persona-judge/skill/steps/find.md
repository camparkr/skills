# Find the personas

Run `find.py` with the paths the user named:

```bash
python3 <skill>/scripts/find.py [PATH ...] [--list FILE] --format json
```

Add `--list FILE` when the user names a list of persona files kept somewhere other than `personas.txt` at the project
root. For pasted text, pass `-` and the text in a quoted heredoc, the only kind of redirect a review uses:

```bash
python3 <skill>/scripts/find.py - --format json <<'TEXT'
...the pasted text...
TEXT
```

It lists each persona with its kind and its branches, as 'Which questions apply' defines them, and each file it sets
aside, with the reason.

On exit 2, a path or the list unreadable, or exit 3, no persona found, stop, because a review of part of the input
would read as a review of all of it.
