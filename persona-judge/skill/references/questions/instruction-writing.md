## Instruction-writing questions

These hold for any instruction an agent reads, in a persona file or elsewhere.

### Checks

**No time-sensitive statements** (*script*). The file says nothing that goes out of date by itself, such as 'until
August' or 'the new API'. *Scores 0 on:* 'Use the v1 endpoint until the migration finishes.' Sources: AN4.

**Consistent with itself** (*reading*, weight 3). No two statements in the file contradict each other. Two statements
contradict when, in one situation, an agent cannot follow both; a general rule beside a stated exception to it, or two
rules for different situations, do not. *Scores 0 on:* a line leaving the final decision to someone else beside a line
telling the agent to make that decision. Sources: AN1, GH1, ST7, ST8.

**Nothing said twice** (*reading*). No sentence restates another sentence or setting in the same file. Two statements
restate each other when the agent would act the same with either one removed. *Scores 0 on:*
the description's sentence repeated as the first rule. No external source was found; the question rests on the
reading that a second statement can drift from the first.

**Leaves known things unsaid** (*reading*). The file spends no lines on what the model already knows, such as what a
file format is or how a library works. Test each line by asking whether the model would act the same with the line
removed; if it would, the line says what the model already knows. *Scores 0 on:* a paragraph explaining what a pull
request is. Sources: AN4.

**Plain emphasis** (*script*). The file emphasises with plain words, not capitals or alarms such as 'CRITICAL' or 'You
MUST'. *Scores 0 on:* 'CRITICAL: You MUST run the tests.' Sources: AN5.

**No placeholders** (*script*). The file holds no unfinished text, such as 'TODO', 'TBD' or a bracketed slot to fill.
*Scores 0 on:* 'Deploy steps: TODO.' Sources: RE2.

**Shows an example** (*reading*). Where the file asks for output in a particular form, it shows an example of that form.
*Scores 0 on:* three paragraphs describing a commit message style and no example message. Sources: GO3, AN4.

### Ratings

**Terms defined where they are used**
*Scale model:* Frequency.
*Places:* Each scale, set of answers or term the file's rules name.
*Meets it:* The file defines it beside the rule.
*Example of a low rating:* A rule to rate findings on a named scale that never says what each step means. Evidence: in the record kept while this skill was built, a persona whose scale was named and not defined rated findings more harshly than the version that defined it.

Sources: RE1.

**Answers defined, edge cases included**
*Scale model:* Frequency.
*Places:* Each closed set of answers the agent returns, such as ratings or recommendations.
*Meets it:* The file says what each answer means and what to return when the work is empty, partial or outside the persona's scope.
*Example of a low rating:* Three recommendations listed with no word on an empty input.

**Its own criteria met**
*Scale model:* Frequency.
*Places:* Each criterion the file sets for the agent's work: a standard the agent's output could be checked against, such as a length, a format or a field the output must hold.
*Meets it:* The file meets that criterion itself.
*Example of a low rating:* A rule requiring every claim to cite a source, in a file whose own claims cite none.

**Instructions an observer can check**
*Scale model:* Frequency.
*Places:* Each instruction.
*Meets it:* Someone watching the agent could tell whether it was followed.
*Example of a low rating:* 'Format code properly' where 'Use 2-space indentation' was meant.

Sources: AN1, GO3.

**What to do, not what to avoid**
*Scale model:* Frequency.
*Places:* Each instruction about the agent's output.
*Meets it:* It says what to produce rather than only what to leave out.
*Example of a low rating:* 'Do not use markdown in your response.'

Sources: AN5.

**Reasons given**
*Scale model:* Frequency.
*Places:* Each rule that limits what the agent does.
*Meets it:* The rule says why.
*Example of a low rating:* 'NEVER use ellipses', with no word on why.

Sources: AN5.

**Each instruction stands alone**
*Scale model:* Frequency.
*Places:* Each instruction.
*Meets it:* It can be understood without reading another instruction first.
*Example of a low rating:* 'Do the same for the other folders', three paragraphs after the first.

Sources: GH1.
