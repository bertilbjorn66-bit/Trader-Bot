# Public Repository Security Boundary

This repository is public. Anything committed here must therefore be treated as public and cloneable.

## Non-negotiable rule

Do not place any of the following in this repository:

- API keys, access tokens, broker credentials, exchange credentials, database passwords, signing keys, or private certificates.
- Raw market-data archives, proprietary order/trade records, private research artifacts, or datasets whose redistribution is not authorized.
- Private model weights, private feature stores, proprietary parameter grids, or unpublished promotion evidence.
- Secrets embedded in workflow files, tests, fixtures, logs, comments, or examples.

## Architecture boundary

The public repository contains only the non-sensitive orchestration, interfaces, validation contracts, and research-safe components.

The protected runtime core must live in a private repository/environment. It may consume this public repository as a dependency, but sensitive intelligence, credentials, private datasets, and private evidence must remain outside the public repository.

A public checkout must never be sufficient to reproduce a private production/research environment.

## Data boundary

Real market data must be acquired through provider adapters and stored outside Git. The public repository may contain provider contracts and deterministic schemas, but not bulk raw-data archives.

Every data snapshot entering the research environment must carry provenance, source identity, acquisition timestamp, as-of timestamp, integrity hash, and an explicit real-data flag.

## Workflow boundary

Public pull requests must not receive privileged credentials. Secrets belong in protected GitHub Actions environments or the private repository. Workflows must use least privilege and may not print secret values.

## Required GitHub protections

For the public repository, enable Dependabot alerts, secret scanning, push protection, and code scanning. GitHub recommends these controls for public repositories.

## Private-core migration

Before any proprietary strategy, broker credential, private dataset, or final promotion evidence is introduced, move sensitive runtime/research assets into a private repository and keep this repository as the public-safe layer.
