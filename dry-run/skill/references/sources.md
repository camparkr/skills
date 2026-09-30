# Sources

Each kind of test, with its source read at its primary location and that source's limit.

| Practice | Source | Limit |
|---|---|---|
| A rehearsal is not the real test | Leon, Davis and Kraemer, 'The role and interpretation of pilot studies in clinical research', *J Psychiatr Res* 45(5), 2011, <https://pmc.ncbi.nlm.nih.gov/articles/PMC3081994/>; HashiCorp, 'terraform plan', <https://developer.hashicorp.com/terraform/cli/commands/plan>; Kubernetes, 'API concepts: Dry-run', <https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run> | Clinical pilots and infrastructure plans, not design pipelines. A plan can differ from what is applied; some admission controllers still act during a dry run |
| Hypotheses fixed before the result | Nosek et al., 'The preregistration revolution', *PNAS* 115(11), 2018, <https://pmc.ncbi.nlm.nih.gov/articles/PMC5856500/> | The guard is a record held outside the author, usually an independent registry. A local commit is a weaker stand-in: it can be rewritten until the project's normal push, which this practice accepts as the point it leaves the author |
| A check shown able to fail | Petrović et al., 'Does mutation testing improve testing practices?', ICSE 2021, <https://arxiv.org/abs/2103.07189> | Mutation testing only, abstract read. It supports the idea in principle; it states no rule |
| A check from outside the author | Huang et al., 'Large Language Models Cannot Self-Correct Reasoning Yet', ICLR 2024, <https://arxiv.org/abs/2310.01798> | Reasoning tasks, not dry runs of changes to code or text |

## Internal evidence only

These rest only on the record kept while this skill was built. No external source was
found for them:

- no objective, no dry run, since without one only conformance can be tested;
- a hypothesis that says what must stay unchanged;
- ordering hypotheses by how late each failure would show;
- where a should-fail case comes from;
- stopping on an inconclusive verdict as on a refuted one, and who decides after each verdict;
- the value of a dry run before an outside review;
- re-reading the intent at source before each dry run;
- the design, decision and specification row of the decision table;
- the fallbacks in `when-things-go-wrong.md`.

No external source was found on dry runs in multi-agent or model-driven design pipelines.

## Not a ground

Do not argue a dry run's value from the rising cost of late defects. Across 171 projects, later fixes took
effort 'not consistently or substantially greater' (Menzies et al. 2017, <https://arxiv.org/abs/1609.04886>),
a finding the authors limit to the projects they studied.
