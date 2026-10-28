# exp-check rules

This file is the checklist that exp-check applies to every piece of text you paste in.
It is written in plain English and sent to the model, unchanged, with every check.
**Whatever you write here is exactly what gets checked** - no code changes needed.

How to write a rule:

- Each rule starts with a line beginning with `## `, followed by a short ID and a name,
  for example `## R07 - Non-targeting siRNA control`. The ID is what the report refers to.
- Below the heading, describe in plain English what to look for, why reviewers care,
  and the default severity (`critical`, `major` or `minor`). The exact wording is up to you.
- To add a rule, copy an existing one and change the text. To remove a rule, delete it.
- Rules that do not apply to the pasted text (e.g. CRISPR rules for a drug-treatment
  experiment) are skipped automatically, so it is fine to keep specialised rules here.
- Optional lines `Satisfied when:` and `Not a finding:` tell the checker where the bar is for a
  rule. They exist because, without them, every unanswered question under `Check:` tends to be
  reported as a problem. Edit them when the checker is too strict or too lenient on a rule.

Severity guide:

- **critical** - a reviewer would likely reject or demand new experiments.
- **major** - must be fixed before submission, but usually fixable with extra analysis or detail.
- **minor** - good practice, clarity, reproducibility.

---

## R01 - Negative and positive controls

Applies to: every experiment with a treatment, transfection, infection, or other perturbation.

Check: Is there a matched negative control (vehicle, mock, untreated, empty vector,
isotype antibody, or equivalent) that is handled identically to the treated samples except
for the variable under test? Where a positive control is feasible (a known activator or
inhibitor, a validated antibody target, a known phenotype), is one included so a negative
result can be interpreted?

Why reviewers care: Without a matched negative control the observed effect cannot be
separated from handling, solvent, or transfection stress. Without a positive control a
negative result is uninterpretable.

Default severity: critical if the negative control is missing; major if only the positive
control is missing.

Satisfied when: the text names a matched comparator for the variable under test (vehicle,
non-targeting siRNA, empty vector, IgG/isotype or input for ChIP/CUT&Tag/Co-IP, a Cas9-expressing
non-targeting line, untreated cells when nothing at all is added to the treated arm). Assume it
was handled identically unless the text states a difference.

Not a finding: a missing positive control when the reported effect is positive (mention it in
notes at most; it becomes a finding only when a negative or null result depends on assay
sensitivity). A missing or mismatched RNAi or CRISPR control is reported under R07 or R09, not
again here.

## R02 - Biological replicates and sample size

Applies to: any quantitative result.

Check: Is n stated, and is it clear what n counts (independent biological replicates such as
separate cultures, animals, or donors - versus technical replicates such as wells, qPCR
triplicates, or repeated measurements of the same sample)? For inferential statistics,
are there at least three independent biological replicates? Do the replicates vary the
right thing (e.g. independent transfections, not three wells of one transfection)?

Why reviewers care: Technical replicates measure pipetting precision, not biological
variability. Statistics computed on technical replicates inflate significance and are a
common cause of rejection.

Default severity: critical if statistics are computed on technical replicates or n < 3;
major if n or its meaning is not stated.

## R03 - Statistical test matches the design

Applies to: any result with a p-value, significance star, or claim of difference.

Check: Does the test fit the design?
- Two groups: t-test (paired vs unpaired must match whether samples are paired) or a
  non-parametric equivalent (Mann-Whitney / Wilcoxon) when normality is doubtful.
- Three or more groups: one-way ANOVA (or Kruskal-Wallis) followed by a post-hoc test with
  multiple-comparison correction - not a series of pairwise t-tests.
- Two factors (e.g. genotype x treatment): two-way ANOVA with the interaction reported.
- Repeated measurements of the same subjects over time: repeated-measures or mixed models.
- Small n with no normality check: a non-parametric test or a justification.
- Count or proportion data: appropriate tests (chi-square, Fisher's exact), not a t-test on percentages.

Why reviewers care: A mismatched test invalidates the p-values on which the conclusion rests.
Uncorrected multiple comparisons are one of the most frequently flagged problems in review.

Default severity: critical.

Satisfied when: the named test fits the groups and pairing the text describes.

Not a finding: a design the text does not state. Report R03 only when the text itself gives both
a test and a design the test does not fit (three or more groups compared by t-tests; several
comparisons with no correction; paired, donor-matched or repeated measurements analysed unpaired;
counts or percentages by t-test; genome-wide results thresholded on unadjusted p), or when a
difference is claimed (a p-value, "significant", "reduced by 45%", "required for") and no test is
named at all. Do not report because the number of groups is unknown, because the factors or
post-hoc test of a named ANOVA are not spelled out, because a Dunnett or Tukey comparison does not
cover a rescue arm, because a non-significant rescue p-value is not "evidence", or because blocking
factors are not in the model.

## R04 - Statistics reporting in legends and methods

Applies to: any figure legend or methods text that reports quantitative results.

Check: Does the legend/method state (a) what the error bars or box plots represent (SD, SEM,
95% CI, range), (b) the exact n and what it counts, (c) the name of the statistical test,
(d) exact p-values or clearly defined thresholds, and (e) how multiple comparisons were handled?
Is "representative of 3 experiments" backed by quantification?

Why reviewers care: Journals' reporting checklists require these items; missing them delays
or blocks acceptance and makes the result impossible to evaluate.

Default severity: major.

Satisfied when: the text presents no quantitative result (a Methods paragraph that names the test
and n but shows no figure, value or p-value has nothing to report here), or the result it presents
defines its error bars, gives p-values or a threshold, and backs "representative" with
quantification.

Not a finding: exact p-values when p-values are given; one- versus two-sided; the terms of a named
model; attrition handling; n of a secondary measurement. R04 applies only where a figure panel, a
value with ± or error bars, a p-value, significance stars or a "representative" image appears.

## R05 - Blinding and randomization

Applies to: animal experiments, histology or imaging that is scored by eye, behavioural
assays, and any subjective quantification.

Check: Were animals or samples randomized to groups? Was the person scoring, counting, or
measuring blinded to group identity? If quantification is automated, is the pipeline
described and applied identically to all groups?

Why reviewers care: Unblinded scoring is a well-documented source of bias, and ARRIVE-style
guidelines make randomization and blinding statements mandatory for animal work.

Default severity: major (critical for in vivo efficacy claims that rest on subjective scoring).

Not a finding: automated or instrument readouts (plate reader, flow cytometry, qPCR, sequencing)
with no blinding statement. Report R05 only for an animal experiment with no randomisation or
blinding statement, or for scoring or quantification done by eye with neither a blinding nor an
identical-automated-pipeline statement.

## R06 - RNAi: at least two independent siRNA/shRNA sequences

Applies to: any siRNA, shRNA, miRNA-mimic, or antisense knockdown experiment.

Check: Were at least two independent, non-overlapping siRNA/shRNA sequences against the
same target used, and does each reproduce the phenotype? If a pooled siRNA was used, was the
pool deconvoluted or backed by a second independent reagent? A single siRNA is acceptable
only when a rescue experiment (see R11) is also shown.

Why reviewers care: Off-target effects of a single siRNA can produce a convincing but false
phenotype. Two independent sequences giving the same result is the minimum standard most
journals and reviewers expect.

Default severity: critical if a single sequence is used without rescue.

## R07 - RNAi: non-targeting control delivered the same way

Applies to: any siRNA / shRNA knockdown experiment.

Check: Is there a non-targeting (scrambled) siRNA or shRNA control, delivered with the same
reagent, at the same concentration, and for the same duration as the targeting siRNA?
"Untransfected" or "mock (reagent only)" alone is not sufficient as the primary control,
although it is useful in addition. For shRNA, is the control an empty or non-targeting
vector produced and selected the same way?

Why reviewers care: Transfection and the RNAi machinery itself change cell physiology
(interferon response, stress, reduced proliferation). Only a non-targeting control delivered
identically separates target-specific effects from these.

Default severity: critical.

Satisfied when: a control RNAi reagent is named ("control siRNA", "non-targeting", "scrambled",
"empty vector", "L4440"); assume it was delivered the same way unless the text says otherwise.

Not a finding: when the text does not describe how the knockdown was made ("knockdown cells"),
R06 and R07 are not applicable. Report R07 when the transfection or transduction is described and
the only comparator is untransfected, mock, parental or untransduced cells, or no comparator is
named at all.

## R08 - Knockdown / knockout validation

Applies to: any RNAi, CRISPR, or other loss-of-function experiment.

Check: Is loss of the target demonstrated at the protein level (western blot,
immunofluorescence, flow cytometry) and, where protein detection is not possible, at the
mRNA level (qPCR with validated reference genes)? Is the validation done in the same cells,
at the same time point, and under the same conditions as the phenotypic assay? For CRISPR
knockouts, is the edit confirmed at the genomic level (sequencing of the locus, or
genotyping showing frameshift alleles) and is protein loss shown rather than assumed? Is
the degree of knockdown quantified (e.g. "70% reduction"), not just "efficient knockdown"?

Why reviewers care: A phenotype without proof of target loss cannot be attributed to the
target. mRNA reduction does not guarantee protein loss; a detected indel does not guarantee
a null allele (in-frame deletions, alternative start sites, exon skipping).

Default severity: critical.

Satisfied when: target loss is shown at the protein level with a number (knockdown) or as
"undetectable" / "absent" (knockout), or at the mRNA level with a number when the text says why
protein could not be measured.

Not a finding: a validation time point, passage or cell state that differs from the readout (48 h
versus 72 h, cells validated before implantation or before differentiation) on its own; mention it
only inside an R08 finding that exists for another reason. R08 does not apply to small-molecule
inhibitor experiments. Report R08 when validation is mRNA-only or DNA-only (genotyping PCR,
TIDE/ICE indel frequency) with no protein, when knockdown is described only qualitatively
("efficient", "a band"), or when a knockdown, knockout or overexpression is used and no validation
is mentioned.

## R09 - CRISPR: multiple guides or clones, and the right controls

Applies to: any CRISPR/Cas9 (or Cas12, base editing, CRISPRi/a) experiment.

Check: Were at least two independent sgRNAs targeting different sites used, or at least two
independent clones derived from different guides? Is it stated whether the experiment used a
polyclonal (pooled, bulk-edited) population or single-cell-derived clones? Is the control a
Cas9-expressing line with a non-targeting or safe-harbour (e.g. AAVS1) guide, rather than
the parental, Cas9-free line? For clonal lines, is the risk of clonal variation addressed by
comparing several clones or by rescue?

Why reviewers care: A phenotype seen with one guide or one clone may reflect an off-target
cut or a clone-specific artefact (clonal drift, aneuploidy, selection bottleneck). Cas9
expression and DNA damage signalling themselves alter cell behaviour, so the control must
carry Cas9 too.

Default severity: critical if only one guide/clone is used without rescue; major if the
Cas9/non-targeting control is missing.

Satisfied when: two independent guides (or clones derived from different guides) and a Cas9- or
dCas9-expressing non-targeting or safe-harbour control are named.

Not a finding: pool-versus-clone status or the number of control clones not spelled out.

## R10 - CRISPR: off-target assessment

Applies to: any CRISPR experiment, especially where the phenotype is central to the claim.

Check: Is off-target risk addressed in at least one of these ways: guides designed with a
tool that scores specificity (with the tool named), top predicted off-target sites sequenced,
concordant phenotype from two independent guides, use of a high-fidelity Cas9 variant, or
rescue by re-expression? Is there any statement about off-targets at all?

Why reviewers care: Cas9 tolerates mismatches; an unassessed off-target cut can produce the
observed phenotype. Reviewers routinely ask for this and journals' checklists request it.

Default severity: major (critical if a single guide is used and no other safeguard is present).

## R11 - Rescue experiment

Applies to: RNAi and CRISPR loss-of-function experiments where the phenotype is a main
conclusion of the paper.

Check: Is the phenotype reversed by re-expressing the target from an siRNA-resistant (silent
mutations in the targeted sequence) or sgRNA-resistant / PAM-mutated cDNA? Is the rescue
construct expressed at a level comparable to the endogenous protein, with an empty-vector
control alongside? If a rescue is not shown, is the omission justified?

Why reviewers care: Rescue is the strongest available evidence that the phenotype is caused by
loss of the intended target rather than an off-target effect. Its absence is one of the most
common requests in revision.

Default severity: major; critical when combined with a single siRNA or a single guide.

Satisfied when: the text describes a rescue with a cDNA stated to be resistant to the reagent
(silent mutations in the target site, PAM-mutated, recoded) that restores the phenotype.

Not a finding: the expression level of the construct, its delivery, the empty-vector arm, or which
siRNA, guide or clone was rescued not being stated. When the text describes only validation or
reagents and reports no phenotype, R11 is not applicable. Report R11 when a rescue uses a cDNA not
stated to be resistant (the reagent would silence it too), or when a loss-of-function phenotype is
the stated conclusion and neither a rescue nor a reason for omitting one is mentioned.

## R12 - Reagent identity, normalization and loading controls

Applies to: all experiments.

Check:
- Antibodies: supplier, catalogue number, clone, dilution, and evidence of specificity
  (e.g. loss of signal in knockout/knockdown).
- Cell lines: source, authentication (e.g. STR profiling), mycoplasma testing, passage range.
- siRNA / sgRNA / primer sequences or catalogue numbers listed.
- Western blots: a loading control (and the band is in the linear range, not saturated).
- qPCR: reference gene(s) named and their stability justified; the quantification method
  (e.g. ddCt) stated.
- Animals: species, strain, sex, age, and approval statement.

Why reviewers care: These are reproducibility requirements on most journals' checklists.
Unvalidated antibodies and unauthenticated cell lines are leading causes of irreproducible
findings, and the lack of a loading control invalidates western-blot quantification.

Default severity: minor (major for a missing loading control or an unvalidated key antibody).

Satisfied when: the key reagents can be identified (an antibody by catalogue number, RRID or clone,
or by a validation statement; an siRNA, sgRNA or primer set by sequence, catalogue number or a
table pointer), the blot has a loading control, the qPCR names its reference gene, and animal work
states strain and approval.

Not a finding: a missing dilution, clone, lot, passage range or supplier of an already identified
reagent; cell-line provenance, authentication or mycoplasma status; primer sequences when the
assays are otherwise identified; kits and instruments. These are at most a remark in notes. Report
R12 for: a quantified or compared western blot with no loading control or total-protein stain;
qPCR as the reported readout with no reference gene named, or with a reference gene the treatment
is known to alter and no stability check; a normalisation that cannot support the claim (depth
normalisation for a claimed global change, a reporter assay with no transfection-efficiency
normalisation); the antibody that produces the main result given with neither catalogue number,
RRID nor clone nor any validation statement (a supplier name alone is not an identifier); an siRNA,
sgRNA or primer set with neither sequence, catalogue number nor table pointer; cells or reagents
the text itself marks as unverified ("gift", "from a collaborator", identity "assumed"); an animal
experiment with no strain or no approval statement.
