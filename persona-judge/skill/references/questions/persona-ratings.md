### Ratings

Two scale-rating models: frequency and quality.

**Rules held in the persona** 
*Scale model:* Frequency. 
*Places:* Each rule the agent applies in every act: a rule that holds whatever the task is, not one tied to a single step or kind of task. 
*Meets it:* The rule is stated in the persona's own files, the ones loaded with it, not only in a file it points to. 
*Example of a low rating:* 'Rate findings on the scale in `severity.md`', with the scale absent. Evidence: in the record kept while this skill was built, a rule moved to another file and pointed to was applied in one run in three. 

Sources: AN1, RE1.

**Directions for when nobody answers** 
*Scale model:* Frequency.
*Places:* Each rule that asks, waits or needs a reply. 
*Meets it:* The rule says what the agent does when no one replies, as in a delegated or unattended run. 
*Example of a low rating:* 'When no level is named, ask', with nothing for a run that has no one to ask. Evidence: a skill review of one persona file in that record found that rule 'can stall a pipeline subagent that has no one to ask'.

Sources: RE1.

**Rules used in every act come first** 
*Scale model:* Frequency.
*Places:* The same places as 'Rules held in the persona'. 
*Meets it:* The rule stands before any procedure, example or reference material in the file. 
*Example of a low rating:* The rating scale a reviewer uses on every finding, set out at the end of a long file after three worked examples. 

Sources: ST5.

**Tools explained** 
*Scale model:* Frequency. 
*Places:* Each tool the file names whose use its rules limit: a tool that can do something a rule forbids, such as a shell in a persona that must change no file. A tool the rules leave as its harness describes it needs no explanation, because the harness already gives its use. 
*Meets it:* The file says when and why the agent uses it within that limit. Whether a setting keeps the tool within the limit is for 'Enforceable rules enforced'. 
*Example of a low rating:* A shell granted to a reviewer with no word on which commands it runs. 

Sources: GO3.

**Commands given exactly** 
*Scale model:* Frequency.
*Places:* Each command the file tells the agent to run. 
*Meets it:* The command is given as it is run, flags and options included. 
*Example of a low rating:* 'Run the tests' where `pytest -v tests/` was meant. 

Sources: GH3.

**The description says when to choose it** 
*Scale model:* Quality. 
*Exceptional:* Puts the main use first, names the requests it is for in words a user would type and says what it is not for. 
*Excellent:* Names those requests in a user's words and says what it is not for. 
*Very good:* Names the requests in a user's words. 
*Good:* Names the tasks in its own terms. 
*Fair:* Names a subject and no task. 
*Poor:* Names a role and no task, such as 'A helpful reviewer'. 
*Very poor:* It is empty or missing. 

Sources: AN3, GO2, OA3, GO3.

**An identity that does the work** 
*Scale model:* Quality. The identity is where the file states the agent's role, such as 'You are…'. 
*Exceptional:* States what the agent does and where its work stops, with no praise. 
*Excellent:* States both, with a word of praise. 
*Very good:* States what the agent does, with no praise. 
*Good:* States what the agent does, with praise. 
*Fair:* Names a role with praise and says nothing of the work. 
*Poor:* Is praise alone, such as 'You are a world-class expert'. 
*Very poor:* States no identity, or names a role at odds with the rest of the file. 

Sources: ST2.