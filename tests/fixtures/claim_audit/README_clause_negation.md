# Clause-scoped negation fixture

The scan is line-based, so these cases are deliberately kept on single lines,
matching how the sentences actually appear in the published HTML.

Must NOT be flagged. This is the disclaimer that shipped on cadclaw.io and was
wrongly flagged when the negation lookback was 30 characters, because the
enumerated list put the "no" 62 characters from the term:

Suitability and required review depend on the assembly, failure modes, and deployment controls, and no return, defect-prevention, or fabrication outcome is guaranteed.

MUST still be flagged, because the negation belongs to a different independent
clause on the other side of a semicolon:

We do not depend on that vendor; delivery is guaranteed.
