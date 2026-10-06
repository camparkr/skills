## Which questions apply, and their weights

All 35 questions are asked of every file, and 111 points are possible: 60 in the persona section and 51 in instruction
writing. A question that does not apply to a persona leaves the total, and the report names it with its reason, so the
points possible are always 111 less those it names. Which questions apply is decided from the file in this order.

**The root: a dedicated persona.** 'A dedicated persona' is answered first. A file that scores 0 on it is set aside
and answers no other question.

**Three branches, read by the scripts.** `find.py` and `check.py` read each from the file, so every reader gets the
same answer:

| Key | Branch | How it is read | When the answer is no, these do not apply | Reason printed |
|---|---|---|---|---|
| delegated | Is the persona delegated, chosen by another agent for a task? | its folder, or front matter holding both `name` and `description` | One job; States its output; The description says when to choose it | not delegated |
| harness | Does its path name a harness? | its folder, such as `.claude/agents/` or `.github/agents/` | Leaves the harness's work to the harness; Declares its tools | path names no harness |
| settings | Does it hold settings that grant or restrict what the agent can do? | a field `tools`, `disallowedTools`, `permissionMode`, `sandbox_mode`, `hooks` or `mcpServers` in its front matter | Bound parts agree with the prose; Permissions fit the job | holds no settings |

**Questions about what the file holds.** Twelve ratings and one check apply only where the file holds their subject.
Each states its test, and the reviewer quotes the line that meets it, or says that no line does:

| Question | Applies when the file holds | Reason printed |
|---|---|---|
| Tools explained | a tool whose use the persona's rules limit, named in a setting or in the prose | no tool whose use the rules limit |
| Commands given exactly | a command the file tells the agent to run | no command to run |
| Directions for when nobody answers | an instruction to ask, wait or confirm | no instruction to ask, wait or confirm |
| Answers defined, edge cases included | a set of answers, a scale or a choice the agent must make | no set of answers, scale or choice |
| Its own criteria met | a criterion the file sets for the agent's work | no criterion set for the work |
| Shows an example | an instruction to give output in a particular form | no instruction to give output in a particular form |
| Rules held in the persona | a rule the agent applies in every act | no rule applied in every act |
| Rules used in every act come first | a rule the agent applies in every act | no rule applied in every act |
| Terms defined where they are used | a scale, a set of answers or a term the rules name | no scale, set of answers or term named |
| What to do, not what to avoid | an instruction about the agent's output | no instruction about the output |
| Reasons given | a rule that limits what the agent does | no rule that limits the agent |
| Instructions an observer can check | an instruction | no instruction |
| Each instruction stands alone | an instruction | no instruction |

Every other question applies to every dedicated persona.

**A check and the rating that follows it.** Where a rating measures how well the file does what a check finds it does,
the rating applies only when the check scores 1, so one missing part costs once. Where the check does not apply, the
rating applies when the file holds its subject.

| Rating | Follows check | Reason printed |
|---|---|---|
| Tools explained | Declares its tools | 'Declares its tools' scored 0 |

**A harness without the field.** Where a harness's files cannot hold what a check looks for, the check does not apply
to them:

| Question | Harness | Reason printed | Source |
|---|---|---|---|
| Declares its tools | Codex | Codex has no tools field | OA2 |

**Weights.** Three checks count 3 points, not 1, because a single instance of each is evidence that the agent may not
do what the file says:

| Check | Why it weighs more | Evidence |
|---|---|---|
| Consistent with itself | the model may follow either of two contradictory statements | vendor rule (AN1, GH1); conflict studies (ST7, ST8) |
| Bound parts agree with the prose | the harness enforces the setting, whatever the prose says | vendor rule (AN2, AN3) |
| Enforceable rules enforced | a rule left to prose binds weakly | study (ST4); vendor rule (AN1) |

Every other check counts 1 and every rating 0 to 6. The report gives the total at equal weights beside the weighted
total, so a reader sees how much the weights move it: weights are a judgement, and equal weights predict about as
well (SC2, SC3).
