# System Design Assessor API

A Python FastAPI application that provides AI-powered assessment for system design solutions.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Configure one LLM provider in `.env`:
   - OpenAI: `LLM_PROVIDER=openai` and `OPENAI_API_KEY=your_key_here`
   - Azure OpenAI: `LLM_PROVIDER=azure_openai`, `AZURE_OPENAI_API_KEY`,
     `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, and
     `AZURE_OPENAI_DEPLOYMENT`
3. Run: `uvicorn app.main:app --reload` or `docker-compose up --build`

The application services depend on a provider-neutral LLM port. OpenAI and
Azure OpenAI request mapping, deployment naming, response normalization, and
authentication are isolated in the provider adapter. Existing `OPENAI_*`
model and token variables remain supported; the generic `LLM_*` equivalents
take precedence when both are present.

### Optional Langfuse observability

The API uses Langfuse's provider adapter integration only when both
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured. Without those
values, or when `LANGFUSE_ENABLED=false`, the service emits no Langfuse
telemetry. Set `LANGFUSE_BASE_URL` to a self-hosted Langfuse URL later without
changing application code. If a selected provider does not have a compatible
Langfuse SDK wrapper installed, the request continues without telemetry.

Tracing is named by product capability (`assessment.evaluate-design`,
`interview.generate-questions`, `interview.critique-answer`,
`recommendations.generate`, and `share.generate-article`) and includes only
safe request dimensions such as counts and feature tags. Prompt and completion
content is excluded by default; enable `LANGFUSE_CAPTURE_CONTENT=true` only
after reviewing the data policy for the environment. Langfuse failures never
fail an AI request.

## API Usage

- **POST** `/api/v1/assess` - Assess a system design
- **POST** `/api/v1/feedback` - Accept anonymous or authenticated product feedback
- **GET** `/health` - Health check  
- **GET** `/docs` - API documentation

### Product feedback storage

Set `DYNAMODB_FEEDBACK_TABLE` (defaults to `diagrammatic_feedback`) and create
the table before enabling feedback in a deployed environment:

## MCP architecture publishing

The MCP service can publish a compiled architecture through the private route
`POST /api/v1/integrations/mcp/architectures`. Configure both
`MCP_INTEGRATION_TOKEN` and `MCP_INTEGRATION_USER_ID` on the API. The route
accepts only `visibility: "public"`, uses an idempotency key to make retries
safe, and returns the existing public URL when the same request is repeated.
OAuth-scoped MCP requests may also provide a validated user subject through the
trusted MCP-to-API hop; those diagrams are saved under that user's account.
The response includes an owner-scoped editor URL when available and a public
SVG preview URL at `/api/v1/public/diagrams/{id}/preview.svg`.

### Product-faithful MCP preview images

The PNG preview route first asks the isolated Diagramwise Chromium renderer to
capture the real public React Flow canvas. Configure
`DIAGRAMWISE_RENDERER_URL` and `DIAGRAMWISE_RENDERER_TOKEN` on this API to
enable it. If the renderer is unavailable, times out, returns a non-PNG
response, or is not configured, the route falls back to the deterministic
server-side preview so architecture creation is not blocked.

This route is intended for the server-to-server MCP service credential. A
user-facing ChatGPT write flow should use OAuth rather than sharing this
service token.

```powershell
python scripts/create_feedback_table.py
```

The table uses an `id` partition key and a `status-createdAt-index` GSI for a
future internal triage queue. Feedback records intentionally contain only
whitelisted product context, not canvas contents.

## Testing

Run tests: `pytest`
