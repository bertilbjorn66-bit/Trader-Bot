# Stage Completion Policy

A stage is either complete or explicitly blocked by a later dependency.

## Immediate-fix rule

Any defect that can be corrected without relying on a future stage must be fixed in the current stage, tested, and included in the active branch before advancement.

## Legitimate standby rule

Work may remain pending only when its correctness depends on a future stage, such as profitability evidence, a future licensed data feed required for a specific intraday domain, or final live-execution authorization.

## Evidence rule

A stage is complete only when its code, tests, documentation, integration boundary, and verification path are on the same branch. A queued or missing CI result is not treated as a pass.
