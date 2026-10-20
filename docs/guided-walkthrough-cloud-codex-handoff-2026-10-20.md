# Guided walkthrough rollout — Cloud Codex handoff

Updated: 2026-10-20

## Mission and stop condition

Finish guided walkthroughs only for the existing Diagramwise problems that currently have no published walkthrough. Do not create new problems, add catalog components, or make duplicate walkthroughs for already-covered problems. The user explicitly wants this backlog to be the end of this walkthrough-authoring effort: after every currently existing problem is either covered or explicitly held with the reason recorded, stop. Do not start a new batch of problem ideas or author new pathways beyond this backlog.

Publish qualifying walkthroughs one at a time so each becomes available to users as soon as it clears every gate. Drafting and independent gates may run in parallel for batches of at most three candidates; publication and live verification remain serialized. Stop when a fresh production reconciliation shows every in-scope problem has exactly one public walkthrough, every public record is retrievable in the product, and all deliberate safety holds are recorded. Do not count a held problem as completed or quietly publish it to reach 100%.

The user wants to move this long-running work to Cloud Codex. Continue from the repository and the machine-readable evidence below; do not repeat completed checks blindly. Preserve all existing dirty and untracked work. The API repository's `AGENTS.md` requires a separate code-review agent before any commit and forbids pushing directly to `master`. The user has requested a scoped branch and commit for this handoff; this note does not authorize a push or merge.

## Completion is a per-problem contract

A draft is not complete, reviewed, published, or user-visible merely because a local test passed. For each problem, require all of the following against the same frozen problem brief and exact walkthrough hash:

1. **Source and schema:** use the problem's current production brief (`id`, title, description, requirements, constraints, hints); validate the existing walkthrough schema and app component catalog. Reuse existing generic/AWS/Azure/GCP components where suitable. Use a custom component only when the catalog truly lacks a fit. Do not invent scale, latency, availability, traffic, or technology requirements.
2. **Structural review:** every required brief anchor is accurately represented by one or more meaningful walkthrough actions. Verify ordering, component types/properties, connections, explanations, and realistic trade-offs. Run the relevant walkthrough contract/fixture tests. A high AI score never excuses a wrong or unsafe guide.
3. **Strict live AI gate:** send the same client-shaped assessment request five times to the configured AI provider. Every run must be HTTP 200, `source=ai`, `score_available=true`, `valid=true`, numeric score at least 95, verdict `strong_alignment`, and full required-anchor coverage. For typed `requirementSpec` briefs, every `scope=core` functional/nonFunctional ID must be supported; extension IDs are not pass-gating. For legacy briefs without a typed spec, every legacy requirement and constraint anchor must be supported. An empty or malformed required-anchor set fails closed. Fallback or unavailable scores do not pass. Preserve request and walkthrough SHA-256 values and all five results. If one run fails, the candidate fails; improve the guide on its merits and rerun all five against the new hash. Never tune content merely to game the score.
4. **Real browser persistence gate:** use the actual local Diagramwise UI on the approved localhost target. Traverse the guide, apply its actions through the product UI, save, reload the route, and verify the saved diagram and applied-step state are restored. Keep the browser evidence tied to the exact walkthrough hash. A local E2E harness is not production and its writes do not reach AWS.
5. **Production publication:** only after gates 1–4 pass, inspect the live row shape and existing API read/write path. Publish just that problem, with a no-overwrite condition for `problem_id`; update any problem `has_guided_walkthrough` flag consistently (prefer an atomic transaction if the existing product workflow requires both rows). Then do a strongly consistent read and verify the public API/product route. Do not call a candidate public based only on a successful AWS write.

If a gate or necessary capability is blocked, record the exact blocker and continue with independent candidates that can safely progress. Do not bypass network, credentials, approval, or browser restrictions.

## Verified state and caveats at handoff (2026-10-20)

### Production inventory

- A fresh AWS CLI read in `ap-south-1` succeeded using the approved AWS access path. `diagrammatic_guided_walkthroughs` is `ACTIVE`.
- The latest strongly consistent, fully paginated primary-key scan found **145 existing problem IDs and 23 walkthrough IDs: 122 problems are currently missing a walkthrough**. It found **0 problem-flag/guide-row mismatches**. Cloud must repeat the inventory before continuing; this count is not permanent. Do not use table `ItemCount` as a coverage count.
- For every next candidate, re-read live problem and guide rows immediately before writing; verify `has_guided_walkthrough` agrees with the guide row. Reconcile any later flag/row mismatches rather than silently overwriting them.
- Four walkthroughs from this rollout have now been conditionally written and verified: Pastebin, Instagram, API Rate Limiter, and Metrics Aggregation. The provenance of the other 19 live guide rows remains unknown.
- The 2026-10-14 inventory at `docs/guided-walkthrough-live-inventory-2026-10-14.json` and older counts of 13/19/132 are historical snapshots. The current count above supersedes them only until Cloud performs its own live read.

At this handoff snapshot, the rollout has **4 newly published-and-verified walkthroughs** and **122 existing problems still missing a walkthrough**. The full live flag/row consistency scan is clean. The latest three candidates each passed structural tests, five identical-input AI runs, browser Apply/Save/Reload, conditional publication, strong readback, and unauthenticated public-route checks. Keep counts separate; do not summarize draft or AI-gated work as published.

### First published candidate: Design Pastebin

- Problem ID: `6901ef1b9420d83630aca85b`; title: “Design Pastebin”. Immediately before publication, a strongly consistent live problem read showed no guide and `has_guided_walkthrough=false`; all six fields `id`, `title`, `description`, `requirements`, `constraints`, and `hints` matched the local fixture used by the gate.
- The live tables observed were `diagrammatic_problems` (partition key `id`) and `diagrammatic_guided_walkthroughs` (partition key `problem_id`), both in `ap-south-1`. The existing public guide row had `version` (S), `totalSteps` (N), `problem_id` (S), `phases` (L), and `steps` (L); `requirementRevision` may also be present. Re-describe/re-read the live schema and a current guide before writing. The application walkthrough route/service inspected for this work was read-only, so a direct DynamoDB transaction may be necessary; verify current code first.
- Current draft: `data/guided-walkthroughs/6901ef1b9420d83630aca85b.json`; 54,409 bytes; 5 phases; 43 lesson steps; Pydantic model validation passed. SHA-256: `fadba26386d20f3fa609d9c5cc6ada0b426943ccea9834c79f9f2cc3f27796e4`. Do not edit or normalize this file after the gate; any content/byte change requires all applicable gates to run again.
- Candidate-only AI gate evidence is preserved in `docs/guided-walkthrough-pastebin-ai-gate-evidence-2026-10-20.json`. It records the five results for the exact hash above and request hash `fa2c1f2b721879bed4f27748ac2a93bfe5fc2da103a16ccbaf300a69b457b04f`: **98, 97, 98, 98, 97**. Every run was HTTP 200, `source=ai`, score available, valid, `strong_alignment`, and had zero unsupported anchors (12 required anchors). The full source batch is intentionally not included because it contains unrelated candidate records; its SHA-256 is retained in the extract. This is local-provider evidence, not a production write.
- Browser gate observation: in the real local Diagramwise UI, all **39/39** design actions were applied, yielding **12 components and 20 connections**. After Save and a full reload, the first accessibility snapshot was captured during loading and temporarily showed 0/0; once the route hydrated, the same UI restored 12 components, 20 connections, and the Guide state showed 39/39 actions applied. Treat the settled, post-hydration state as the observed persistence result; the immediate 0/0 snapshot was not the final state.
- Harness caveat: the isolated API harness at `127.0.0.1:8019` is local-only and reports `awsWrites=0`. Its trace showed `/api/v1/canvases` returning 404, while attempt reads/creation worked. The Pastebin reload restored via the attempt path, but Cloud should preserve the trace and confirm the actual save/read route when it reruns browser E2E for the next candidates. Never count a harness write as a production publication.
- Publication succeeded through `TransactWriteItems`: the guide Put was conditional on no existing `problem_id`, and the problem flag update was conditional on the existing problem row with a false flag. Strongly consistent readback matched the exact guide source and showed the flag true. A post-write full scan found 145 problems, 20 guides, 125 missing, and 0 flag/row mismatches.
- The public route `https://diagramwise.com/playground/6901ef1b9420d83630aca85b` was opened without authentication. The problem page loaded; its Guide tab displayed all 5 phases and 43 steps, ready at 0/39 design actions for a new user. This confirms user visibility, not a production Apply/Save/Reload test; that persistence proof remains local-only.
- The durable evidence is `data/e2e-20261020-walkthrough-ai-batch-03/pastebin-publish-verification.json`. The guide remains version `1.0.0-review-draft`; do not change its version/content without rerunning gates.

### Newly published batch: Instagram, API Rate Limiter, and Metrics Aggregation

- Candidate drafts are `data/guided-walkthroughs/{problem-id}.json`. Their exact SHA-256 values, AI request hashes, scores, browser attempt counts, production readback, and public URLs are captured in `docs/guided-walkthrough-publish-verification-2026-10-20.json`.
- Exact five-run AI evidence is `data/e2e-20261020-next3-ai-01/strict-gate-5x-batch-01.json`: Instagram (`6901ef1b9420d83630aca85c`) scored 97, 98, 97, 98, 98; API Rate Limiter (`6901ef1b9420d83630aca85f`) scored 98 five times; Metrics Aggregation (`6901ef1b9420d83630aca860`) scored 98, 97, 98, 98, 98. All 15 runs were HTTP 200, AI source, score available, valid, at least 95, `strong_alignment`, and supported all anchors. The draft hashes match the evidence.
- Focused structural tests passed: 6 for Instagram and 10 for Rate Limiter plus Metrics Aggregation (16 total). A concurrent pytest cache warning (`WinError 183`) did not affect the passing tests.
- The real browser UI used an isolated local frontend at `127.0.0.1:5181` and guarded API harness at `127.0.0.1:8021`, run data `data/e2e-20261020-next3-harness-01/`. It recorded exactly three in-memory attempts and `awsWrites=0`. After applying every canvas action and decision, Save/Reload restored: Instagram 18 nodes/29 edges and 47/47 actions; Rate Limiter 9 nodes/9 edges and 19/19 actions; Metrics Aggregation 11 nodes/12 edges and 28/28 actions. The raw local `session.json` is intentionally not in this handoff branch; the committed publish-verification JSON preserves its per-problem counts. Cloud should run a fresh browser gate for each new candidate and must not depend on access to this old session file.
- Production publication used `TransactWriteItems` for each problem: guide Put required the guide key to be absent; the problem-flag Update required the exact current title, description, requirements, constraints, hints, category, difficulty, and a false flag. Strongly consistent reads exactly matched each source guide and showed each flag true. A full consistent scan then found 145 problems, 23 guide rows, 122 missing, and zero mismatches.
- Public pages loaded without authentication and their Guide panels showed the expected step counts (Instagram 52, Rate Limiter 23, Metrics Aggregation 35) at 0 applied actions for a new visitor: `https://diagramwise.com/playground/6901ef1b9420d83630aca85c`, `https://diagramwise.com/playground/6901ef1b9420d83630aca85f`, and `https://diagramwise.com/playground/6901ef1b9420d83630aca860`.

### Other local evidence, safety, and machine state

- The evidence folder `data/e2e-20261020-walkthrough-ai-batch-03/` contains screening and strict-gate output for many IDs. A prior local parse counted 87 IDs and 40 latest strict-pass results; those numbers are **not completion counts** and may be stale. Recompute from machine-readable results. Aside from the separately documented Pastebin candidate, a strict AI pass alone is not evidence of structural, browser, or publication completion.
- `docs/guided-walkthrough-assessment-gates.json` is the policy reference: 5 runs, minimum 95, `strong_alignment`, all runs must pass, no fallback passes, and no publication on a failed gate.
- `docs/guided-walkthrough-safety-holds.json` records problem `6901ef1b9420d83630aca87c` (“Design a Distributed Botnet”). The user approved defensive reframing, but the current problem brief still contains offensive capabilities. Do not provide command-and-control, stealth, evasion, or takedown-resistance design. If the existing brief cannot be handled as a genuinely defender-facing detection/containment exercise without contradicting it, keep it unpublished and record it as a hold, not as completed. Do not create another problem as a workaround.
- The latest local harness run used port 8021 and the frontend used port 5181; the evidence directory above records `scope=local-only` and `awsWrites=0`. These local processes, tabs, and sessions do not move to Cloud. Verify any process owner before reuse or termination.
- The API repository has extensive pre-existing modified and untracked work (including `scripts/e2e_assessment_app.py`, fixture/test files, simulation code, and many candidate/test files). This handoff packet is isolated on branch `codex/guided-walkthrough-cloud-handoff-2026-10-20`, based on `develop`; preserve unrelated work. Inspect `git status` in both repositories before edits; do not clean, reset, mass-stash, or overwrite user work.
- The API and frontend are **separate repositories**: API `D:\satya\ngExp\diagrammatic\diagrammatic-api`, frontend `D:\satya\ngExp\diagrammatic\diagrammatic`. The parent folder is not a Git repository. Both checkouts are needed to run the UI persistence gate.
- The handoff change set (this note, four newly published guide drafts and focused tests, their gate/verification evidence, and only the harness/fixture/policy files needed to continue) is on local branch `codex/guided-walkthrough-cloud-handoff-2026-10-20`, based on `develop`; it has **not been pushed**. A Cloud task on the remote default branch will not automatically see it. No push or merge has been performed. Before continuing, make this branch available to Cloud through an explicitly authorized push/shared workspace snapshot, then verify both repositories and the exact artifacts are accessible. Do not overwrite or discard the unrelated local changes. If the artifacts are unavailable, stop and ask the user to expose them; do not recreate or claim prior gates from memory.
- The local browser/API sessions and credentials do not automatically move with a Cloud task. Verify the approved AWS/Azure credentials and browser/E2E capabilities before acting. Do not copy credentials into this document or task prompt. Local ports, tabs, processes, and uncommitted files are not assumed to exist in Cloud; if access is absent, report the exact blocker rather than weakening a gate.

## Workspace map

- API repository: `D:\satya\ngExp\diagrammatic\diagrammatic-api`
- Frontend repository: `D:\satya\ngExp\diagrammatic\diagrammatic`
- Candidate guide drafts: `diagrammatic-api/data/guided-walkthroughs/*.json`
- Frozen local problem fixtures: `diagrammatic-api/tests/fixtures/walkthroughs/problems.json`
- Local strict-gate runner: `diagrammatic-api/scripts/run_walkthrough_ai_gate.py`
- Isolated E2E API harness: `diagrammatic-api/scripts/e2e_assessment_app.py`
- Strict policy: `diagrammatic-api/docs/guided-walkthrough-assessment-gates.json`
- Historical live inventory: `diagrammatic-api/docs/guided-walkthrough-live-inventory-2026-10-14.json`
- Safety holds: `diagrammatic-api/docs/guided-walkthrough-safety-holds.json`
- Existing component definitions/UI catalog: inspect the frontend TypeScript component catalog and the `system-design-problem-builder` skill before authoring; do not add components for this rollout.

## Cloud continuation sequence

### 1. Reconcile production first

Confirm the active AWS identity/region through approved tools without printing credentials. Read the live schemas and records from `diagrammatic_problems` and `diagrammatic_guided_walkthroughs` in `ap-south-1`; the known historical keys are `id` and `problem_id`, respectively, but verify them live. Fully paginate strongly consistent scans (table `ItemCount` is not a reliable current coverage count). Join IDs, flags, and walkthrough rows and report:

- total existing problems;
- public walkthrough rows;
- problem flags set;
- flag/row mismatches;
- exact missing IDs;
- duplicate/invalid IDs, if any.

Fetch and freeze the exact production brief for each selected ID. Never infer a current brief from a stale local fixture. Keep reads read-only until a particular candidate passes every gate.

### 2. Reconcile local evidence before spending more AI calls

Parse each `strict-gate*.json` and screening file, select the newest result per problem by evidence timestamp, and verify `passed`, all five per-run checks, stable hashes, and current draft hash. Treat a mismatch or incomplete file as not passed. Start with candidates having current strict-pass evidence but no browser pass; then work through remaining missing IDs in independent batches of at most three candidates. The runner accepts parallelism up to six, but prior provider reliability favored three; do not increase concurrency to the point that timeouts/429s create noisy retries.

Do not claim progress in “reviewed” counts. Report separate counts for: production published and verified; strict five-run AI passed for current hash; browser Apply/Save/Reload passed for current hash; screened only; failed/held; and not started.

For a fast, recoverable rollout, work on up to three missing problem IDs in parallel for brief review, authoring, structural tests, and AI gates. Keep output directories unique per run. Browser sessions may run in parallel only if each has isolated browser storage and API state; otherwise serialize those sessions. Publish and verify exactly one candidate at a time. After each publication, update the counts and continue without waiting to accumulate a batch.

### 3. Author and verify a candidate

Use the established walkthrough format and existing provider catalog. Map each functional and non-functional requirement to actions that actually implement or explain it. Distinguish requirements from assumptions and state alternatives/trade-offs. Use defensive reframing only when the source brief is explicitly unsafe, and keep such candidates held until the problem owner approves a revised brief.

Run focused structural tests. For five-run assessment, use a unique, new child directory under API `data/`; never reuse a harness run directory because the harness refuses to overwrite it. The strict runner is:

```powershell
& '.\.venv\Scripts\python.exe' scripts\run_walkthrough_ai_gate.py `
  --ids ml_008 ml_009 `
  --rounds 5 --parallelism 3 `
  --base-url http://127.0.0.1:8019 `
  --output data\e2e-<unique-run>\strict-gate-5x-batch-01.json
```

Use the actual candidate IDs and unique output path. The runner sends the client-shaped request to the loopback harness; it does not write AWS. Do not put credentials in command output or evidence files.

For localhost E2E, start the API only with the explicit live-provider mode and a **new child path under `data/`**:

```powershell
$env:E2E_LIVE_PROVIDER='1'
$env:E2E_RUN_DIR='<API absolute path>\data\e2e-<unique-run>'
& '.\.venv\Scripts\python.exe' -m uvicorn scripts.e2e_assessment_app:app --host 127.0.0.1 --port 8019
```

The harness guards the AWS resource and is meant to stay loopback-only. Start the frontend with both API variables pointed at that harness:

```powershell
$env:VITE_API_URL='http://127.0.0.1:8019'
$env:VITE_ASSESSMENT_API_URL='http://127.0.0.1:8019'
npm run dev -- --host 127.0.0.1 --port 5190
```

If a port is already in use, identify its owner before choosing another port and update both the browser URL and API base consistently. In the real UI, open `/playground/<problem-id>`, apply the guide, save, reload, and capture evidence that the expected node/connection counts and applied-step state persist. Stop only the processes started for this run afterward.

### 4. Publish one candidate, verify, then continue

Before writing, inspect the current `DynamoDBService` methods, walkthrough read route, problem flag behavior, live row shape, and current guide row. Use the product's supported publication path if present. If the workflow requires direct CLI writes, construct the exact item from the established schema, prevent overwriting an existing `problem_id`, and update related flags atomically where needed. Then strongly read both records, query the public API, and load the public problem route to verify the Guide tab contains the expected walkthrough. Record hashes, timestamp, commit/worktree version, AWS verification, and public-route evidence. Publish the next candidate only after the prior one is confirmed or safely classified as blocked.

If AWS calls return endpoint/network errors, stop production writes and surface the exact error. Continue only safe local work; do not use another channel or proxy to get around the egress restriction.

## User-facing handoff prompt

> Continue the existing Diagramwise guided-walkthrough backlog using `diagrammatic-api/docs/guided-walkthrough-cloud-codex-handoff-2026-10-20.md`. First verify that this Cloud task can access branch `codex/guided-walkthrough-cloud-handoff-2026-10-20` and its committed handoff packet, as well as both repositories. If the branch is not available, stop and ask the user to share it; do not search for or depend on local dirty/untracked artifacts, and do not reconstruct prior gates from memory. Reconcile production before proceeding. Latest verified snapshot: 145 problems, 23 guides, 122 missing, 0 flag/row mismatches. Pastebin (`6901ef1b9420d83630aca85b`), Instagram (`6901ef1b9420d83630aca85c`), API Rate Limiter (`6901ef1b9420d83630aca85f`), and Metrics Aggregation (`6901ef1b9420d83630aca860`) are already published and publicly verified; do not duplicate them. Work only on remaining existing problems. Reuse the component catalog. For each candidate, freeze the exact live brief, structurally validate the guide, require five identical-input live AI runs with every run valid, score at least 95, `strong_alignment`, and full required-anchor coverage (all typed core IDs, or all legacy requirement/constraint IDs for a legacy brief), then complete browser Apply/Save/Reload for that same guide hash. Prepare independent candidates in batches of at most three; publish and verify one at a time with no-overwrite protection. Keep failed or unsafe candidates unpublished. Report separate counts for AI-gated, browser-gated, published/verified, failed/held, and not started. After all existing problems are covered or explicitly held, stop authoring. The user authorized the AI data transfer and publication of qualifying candidates; use only approved Cloud credentials/tools and stop if access or permission is missing.
