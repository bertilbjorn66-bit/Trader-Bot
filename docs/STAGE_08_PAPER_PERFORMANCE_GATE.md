# Stage 08 — Independent Paper-Performance Gate

Stage 07 made the repository capable of consuming real current quotes without transmitting broker orders. Stage 08 adds the missing distinction between **engineering readiness** and an actual **paper-performance pass**.

## A campaign is not a pass merely because the runner works

A real paper campaign must bind a frozen strategy snapshot to one immutable `PaperCampaignSpec`. The campaign has an explicit UTC start and end, an observation minimum, and the existing frozen evaluation contract.

The independent `PaperPerformanceGate` produces one of four meaningful outcomes:

- `INCOMPLETE`: the real observation period has not completed or the minimum evidence requirements have not been met;
- `FAILED`: the completed period violates a promotion condition, including non-positive expectancy, profit factor at or below 1, loss-gate failure, or specification mismatch;
- `COMPLETE`: the real period completed and passed every configured paper-performance condition.

## Promotion conditions

A paper campaign can only pass when all of the following are true:

1. the campaign window is complete;
2. the accepted-observation minimum is met;
3. the evaluation exists and uses the exact frozen evaluation-specification fingerprint;
4. the minimum closed-trade requirement is met;
5. the evaluation's loss gate is passed;
6. expectancy is strictly positive;
7. profit factor is strictly greater than 1.

The campaign specification itself is fingerprinted. Changing the strategy snapshot, research reference, evaluation contract, campaign dates, observation minimum, expectancy threshold, or profit-factor threshold creates a different campaign.

## Real-data boundary

The campaign gate does not download historical data and does not calculate a new strategy. Stage 07 remains responsible for consuming current quotes. The campaign gate only evaluates the resulting real paper evidence.

A passing engineering CI check therefore never masquerades as a passing paper campaign. Actual future observations are required.

## Safety boundary

Broker transmission remains disabled. A paper-performance pass is only a prerequisite for the later shadow-execution gate; it does not authorize live trading.
