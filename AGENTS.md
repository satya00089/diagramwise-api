# Agent instructions

## Delivery workflow

Before every commit, have a separate code-review agent inspect the exact changes being committed. Address the findings before committing. If no independent review agent is available, stop before committing and report that blocker.

When delivering a requested code change:

1. Work from `develop`.
2. Stage only the files belonging to the requested change; preserve unrelated worktree edits.
3. Get a separate code-review agent to review the staged diff before each commit, and resolve its findings.
4. Commit on `develop` with a focused conventional-commit message.
5. Push `develop` to `origin/develop`.
6. Open or update a pull request from `develop` to `master` for this API repository. Never push or merge directly to `master`.
7. Verify the pushed `develop` commit and PR status. Leave `develop` checked out.

Do not rewrite or discard unrelated user changes.
