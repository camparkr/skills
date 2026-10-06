# Run the script checks

Run `check.py` once, naming every file 'Settle the files each persona loads' settled for each persona, so the checks
reach every file a persona loads:

```bash
python3 <skill>/scripts/check.py [PATH ...] --format json
```

For pasted text:

```bash
python3 <skill>/scripts/check.py - --format json <<'TEXT'
...the pasted text...
TEXT
```

Its rows set every check marked *script*. Exit 1 is the usual result: a check was not met, and the report shows which.
On exit 2, a fault in a file or the table, or exit 3, nothing to check, stop, because the checks it skipped would be
missing from the score.
