# Step 0: review question and eligibility criteria

Based on PRD sections 5 and 6.5. This is the example review protocol, not medical
advice or a claim about treatment effectiveness. The rules must also work with
unseen review topics supplied through the active query.

**Review question:** In adults with major depressive disorder, does sertraline,
compared with placebo or another antidepressant, reduce depression severity?

| PICO element | Review definition |
|---|---|
| Population | Adults with major depressive disorder |
| Intervention | Sertraline |
| Comparator | Placebo or another antidepressant |
| Outcome | Change in depression severity, including HAM-D or MADRS scores |

Publication date range: **2016-01-01 through 2026-10-27** for the initial demo.
Adjust the end date when running the review. These dates constrain publication
dates; they do not establish study eligibility or treatment quality.

## Search versions

**v1**

```text
("major depressive disorder"[tiab] OR "depressive disorder"[tiab]) AND sertraline[tiab] AND placebo[tiab]
```

**v2: broaden the intervention group**

```text
("major depressive disorder"[tiab] OR "depressive disorder"[tiab]) AND (sertraline[tiab] OR escitalopram[tiab]) AND placebo[tiab]
```

Saving v2 creates a new version; v1 remains available. Show PubMed's actual
`querytranslation` and hit count beside each version. Do not put example counts
into the live review. The v2 expansion changes the review scope and requires a
reviewer to accept it; it is included to demonstrate the query-change loop.

## Criteria and reasons

| Key | Decision rule | Reason | Evidence / method |
|---|---|---|---|
| `human_adult_mdd` | Include human adults with MDD | This is the target population | Review definition; query-concept matching supports relevance, but a reviewer must verify age and diagnosis |
| `has_comparison` | Include a relevant intervention/comparator comparison | A comparison is needed to answer the question | Review definition; query terms and PICO suggestions assist the reviewer rather than establish study design |
| `non_human` | Exclude Animals MeSH without Humans | The question concerns people | Metadata first; if MeSH is not decisive, bounded rat/rats/mice/mouse/murine/zebrafish/in-vitro keywords |
| `non_english` | Exclude explicit non-English language | The review team cannot verify other languages | Language metadata first; seeded language detection when missing, confidence ≥0.90 with ≥20 letters; uncertain language is Maybe |
| `case_report` | Exclude case reports | An individual case cannot establish an average comparative effect | Case Reports publication type; case-report title regex fallback |
| `simulation` | Exclude simulation/modeling studies | The question concerns measured patient outcomes | Own keyword algorithm: in silico, Monte Carlo, simulation, computational model |
| `no_abstract` | Maybe for a missing/empty abstract | Abstract-level eligibility cannot be assessed | Stored abstract field |

The first two rows define the protocol; they are not separate implemented binary
exclusion functions. The implemented relevance baseline uses pipeline-supplied
`query_groups`: at least one term from every concept group gives Include; missing
groups give Maybe with the missing concepts named. Topic terms are confined to
the query/protocol/fixtures. They are not hardcoded into screening or PICO code.

Any matching active exclusion outranks Maybe; the caller's criterion order chooses
the first matching exclusion. Every Exclude stores a reason and criterion key.
No abstract remains Maybe under PRD S6 even if its named criterion is disabled.
Humans MeSH prevents animal-keyword exclusion, but does not disable other rules.

| Criterion | Metadata field used | Fallback algorithm | Known failure cases |
|---|---|---|---|
| `non_human` | `mesh=Animals` without `Humans` | Animal/in-vitro word boundaries in title or abstract | Negated or background animal mentions can falsely exclude; `Animals` plus `Humans` does not exclude |
| `non_english` | Scalar `language` | Seeded `langdetect` on >=20 letters at >=0.90 confidence | Short, mixed-language or non-Latin text may be uncertain; multiple languages are not preserved by the current scalar parser |
| `case_report` | `pub_types=Case Reports` | Case-report title pattern | Case reports without type or title phrase can be missed; phrase in unrelated context can mislead |
| `simulation` | None | In-silico, Monte Carlo, simulation and computational-model patterns | Mentioning a model as background can falsely exclude; synonyms can be missed |
| `no_abstract` | Empty/missing `abstract` | None; Maybe for manual review | Missing text does not establish ineligibility |
| Query relevance (Include/Maybe) | No eligibility metadata | Match query concept groups against title/abstract | Synonyms and negation can change meaning; missing groups remain Maybe |

Screening reasons carry a bracketed source tag: `[metadata: field=value]` or
`[algorithm: rule, matched 'snippet']`. The source is the evidence for the
returned label, not a claim that every other field was validated.

## Human review and evidence limits

Reviewers can change labels, resolve duplicate pairs, edit PICO spans, add notes,
and undo through new audit entries. Machine reruns must preserve that work.
PICO spans are rule-based suggestions against exact stored text, not a trained
biomedical interpretation. Inspect the actual text before accepting a tag.

The 80 current screening cases and 10 duplicate pairs are explicitly synthetic.
The screening baseline agrees with 77/80 synthetic reference outcomes; three
documented keyword-context false positives remain. This is development coverage,
not an estimate of PubMed precision or recall. Populate and independently label
60–100 real fetched abstracts using `fixtures/pubmed_screening.template.json`
before reporting real-data performance.
