# Query optimization migration

The API changes use a collaborator membership table and two DynamoDB indexes.
Provision and backfill these before deploying the API code that reads them.

## Migration order

1. Pause problem catalog writes, diagram sharing, permission changes, collaborator
   removal, diagram deletion, attempt saves and assessments, and publish/unpublish
   writes for the migration window.
2. Set AWS credentials and table-name environment variables for the target account.
3. Run `python scripts/migrate_query_optimization.py` from this repository.
4. Wait for `diagrammatic_problems/slug-index` and
   `diagrammatic_problem_attempts/leaderboard-index` to become `ACTIVE`. The
   script waits for both indexes and backfills existing memberships and public
   leaderboard entries.
5. Deploy the API version that reads the new indexes, then resume writes.

The script is safe to rerun after an interrupted run. It creates
`DYNAMODB_DIAGRAM_SHARES_TABLE` when it is missing, with `collaboratorUserId` as
the partition key and `diagramId` as the sort key. It stops if an existing
table or index has an incompatible key schema or projection. The application
reads the shares table for shared-diagram access; owner collaborator lists
remain in the diagram item and are updated atomically with the membership row.
It stops if a problem or attempt changes during a conditional backfill.

Before creating the problem slug index, the script fills missing or empty slugs
from each row's title using the same normalization as the API model. Existing
non-empty slugs are preserved. It checks the effective slugs across the catalog
before writing and stops if any duplicate, malformed slug, or title that cannot
produce a usable slug would make the index ambiguous or invalid; resolve those
catalog records and rerun the script.
The problem slug index is keyed by `slug`. The leaderboard index is keyed by
`leaderboardProblemId` and sorted by numeric `leaderboardScore`. Only public
attempts with a qualifying assessment receive those attributes.

Keep those writes paused until the new API deployment is complete. The
migration requires permissions to describe and update the problem and attempt
tables, create and write the shares table, scan the diagrams table, and update
attempt items. It adds missing problem slugs and index/membership attributes;
it does not delete or rewrite existing slugs, diagram content, or attempt
content. This workspace change does not run the migration against AWS.
