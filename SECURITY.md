# Security Policy

## Scope

This repository is private and may eventually contain infrastructure capable of interacting with financial accounts. Treat credentials, account identifiers, broker endpoints, cached market data, and logs as sensitive.

## Rules

1. Never commit API keys, broker credentials, account secrets, private certificates, or `.env` files.
2. Live trading remains disabled by default in code and configuration.
3. Research decisions are not execution authorization.
4. All external data must pass schema and integrity validation before entering research.
5. Provider failures must fail closed; they must never be converted into synthetic prices.
6. Stale or ambiguous market data must result in `NO_TRADE` rather than a guessed decision.
7. Historical tests must prevent look-ahead and target leakage.
8. Changes affecting risk, execution, credentials, or provider parsing require tests and review before merging.

## Reporting

For a private security concern, do not open a public issue containing credentials or exploitable details. Rotate any exposed credential immediately and use the repository's private security/reporting channel.
