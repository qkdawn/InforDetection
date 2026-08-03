# Evaluation goal

Judge whether an item is ready to be expanded under the current topic. Do not confuse completeness with value: a brief observation can be excellent when it already contains a distinctive relationship worth developing.

# Evaluate in this order

1. **Source signal:** What concrete fact, relationship, behavior, or anomaly is actually present?
2. **Topic value:** What does that signal offer the current topic? Use the topic focus when supplied. Without one, default to a source-bound participatory or creative experience suitable for game ideas; scientific, commercial, or cultural interest alone is not enough.
3. **Source binding:** Does the value depend on this source's specific relationship, or would the same explanation fit many unrelated items?
4. **Core invention:** Would expansion require inventing the key causal relationship or value claim that makes the item worthwhile?

It is acceptable to invent a setting, role, controls, presentation, or prototype details during enrichment. It is not acceptable to invent the core relationship on which the item's value depends.

# Scoring rubric

- **9-10: Directly expandable.** The source already contains a distinctive, topic-relevant relationship. Its value is source-specific, and expansion does not require inventing a core cause, conflict, capability, or experience.
- **7-8: Strong seed.** The material may be brief or incomplete, but the key relationship and its topic value are already present. Enrichment may design the concrete form without changing why the item matters.
- **6-6.9: Candidate.** The signal may be valuable, but a key fact, context, or relationship must be traced or combined with other material before responsible expansion. Preserve it, but do not enrich it yet.
- **0-5.9: Reject for now.** The item lacks usable topic value, depends on a generic interpretation, or would require inventing the core relationship that makes the output work.

# Guardrails

- A short source is not automatically weak. Do not inventory routine omissions such as methods, sample size, effect size, or implementation details merely because the item is brief.
- Missing detail matters only when it changes the key relationship, makes the source's wording ambiguous, or forces the model to invent the premise needed for expansion.
- For items scoring 7 or above, do not append generic evidence disclaimers to the reason. If a decisive limitation remains, name only that specific limitation and explain why the item can still be expanded.
- A named person, organization, study, or product does not by itself create source binding. The value must depend on the source's distinctive relationship or anomaly, not its proper nouns.
- Count only relationships stated in the supplied item. Plausible consequences inferred from general knowledge may guide later design, but they cannot be used to prove source binding or direct readiness.
- Remove the source-specific objects, relationships, and anomaly from the proposed value. If the explanation still means almost the same thing, score at most 5.9.
- If the model must invent the decisive causal relationship, conflict, capability, or experiential premise, score at most 6.9.
- Under the default game-inspiration topic, the reason must identify what a participant could uniquely judge, discover, express, perform, create, or risk because of the source-specific relationship. If it can only describe why the fact is interesting to learn about, score at most 5.9.
- Score the material, not the model's ability to write an attractive pitch.

# Calibration

- A clearly stated, distinctive relationship can score 7-8 even when research methods or implementation details are missing.
- A promising fact that needs an unstated causal step or experiential relationship belongs at 6-6.9.
- A concrete job post, origin anecdote, ranking, or named case with no participatory or creative relationship belongs below 6 under the default game-inspiration topic.

Write a concise reason that names the source-specific relationship and its topic value. Mention missing information only when it materially caps the score below 7; never add a routine list of absent methods, samples, effect sizes, or causal proof. Write the summary in plain language. Tags should describe the concrete signal or topic value, not internal technical models.
