# Capacity simulator rollout

The capacity simulator is a bounded educational estimate for the URL shortener exercise. It does not model queueing, latency, timeouts, failures, or provider benchmarks. The API flag is off by default.

## Before enabling

1. Deploy the API and frontend changes to staging with `SIMULATION_CAPACITY_ENABLED=false`.
2. Give the provisioning identity DynamoDB `CreateTable`, `DescribeTable`, `DescribeTimeToLive`, and `UpdateTimeToLive` permissions for the target table. Run `python scripts/create_simulation_runs_table.py` with the intended `AWS_REGION` and `DYNAMODB_SIMULATION_RUNS_TABLE`. The script uses boto3's standard credential chain, such as an attached IAM role or AWS environment credentials; it does not need the API's other secrets.
3. Give the API runtime identity `Query`, `PutItem`, and `DeleteItem` permissions on that table. The table uses `userId` as its partition key and `runSlot` as its sort key; TTL is enabled on `expiresAt`.
4. Configure the API with a shared Redis endpoint in `REDIS_URI`. Configure `TRUSTED_PROXY_IPS` with only the reverse proxy addresses that set or appear in `X-Forwarded-For`. Leave it empty for a directly exposed API. The API walks the forwarding chain from the trusted end and uses the first untrusted address, so the edge proxy must append the connecting client address or replace incoming forwarding headers. The AI preparation quota is keyed by a one-way hash of that address; no raw IP is stored in Redis.
5. Confirm that the existing API request-rate middleware, Redis availability, and DynamoDB permissions are healthy in staging. Exercise deterministic and AI-assisted preparation, signed-in save/list/delete, request-size rejection, and per-user ownership.
6. Enable `SIMULATION_CAPACITY_ENABLED=true` in staging. Watch API 4xx/5xx rates, Redis errors, AI provider usage, DynamoDB throttling, and save conflicts during a limited pilot before enabling it for production users.

## Runtime limits

- Preparation request bodies are capped at 256 KiB; saved-run bodies are capped at 56 KiB before JSON parsing. Graphs sent to AI path preparation are further capped at 64 KiB after deterministic path recognition.
- Each saved snapshot is limited to 48 KiB, 50 active runs per account, and a 90-day expiry. Users must delete a saved run before saving another when at the limit. DynamoDB TTL deletion is asynchronous; reads ignore expired records immediately.
- AI-assisted preparation requires shared Redis reservations, is limited to 10 requests per actor per hour and 500 requests globally per hour by default, and allows 3 concurrent requests across API instances by default. Redis protection fails closed for AI requests. Deterministic preparation and local calculations can continue if Redis is unavailable.
- The global request-rate middleware remains an additional limit. Tune these defaults using staging traffic and provider budgets before broad release.

## Rollback

Set `SIMULATION_CAPACITY_ENABLED=false` to disable new preparation and saved-run writes without a redeploy. Existing saved runs remain readable and can be deleted. Keep the table while users may still need those records; TTL removes them after their expiry. To remove the table, first confirm that saved runs no longer need retention, then use the normal infrastructure change process rather than deleting it as part of application rollback.

Production activation is an environment change and must be performed after the staging checks above. This repository change does not enable the flag or create cloud resources automatically.
