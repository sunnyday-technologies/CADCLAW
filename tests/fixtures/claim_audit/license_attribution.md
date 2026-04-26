# Sample README for MED-3 license-attribution fixture

This is a v0.7 fixture testing license-aware claim_audit.

## Attribution

V-Slot component CAD models in `CAD/Components/` are based on
[OpenBuilds](https://openbuilds.com) designs and are licensed under
CC BY-SA 4.0.

Some helpers borrow patterns from the MIT License-licensed `pyramid` library.

## Real content

We removed JB Weld from the assembly in 2026-04. The "OpenBuilds" string
on line 7 above is a license attribution and must NOT be flagged — its
removal would constitute a license violation.

But this line legitimately mentions OpenBuilds outside of an attribution
context, and SHOULD flag if "OpenBuilds" is in stale_terms.
