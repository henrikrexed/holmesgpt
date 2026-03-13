# OpenTelemetry Observability

HolmesGPT includes built-in OpenTelemetry (OTel) instrumentation that produces **distributed traces** and **metrics** for every investigation. This enables end-to-end observability from user prompt through LLM calls and MCP tool execution.

## Enabling OpenTelemetry

OTel instrumentation activates automatically when the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable is set. No code changes or flags are needed.

### CLI

```bash
# Install with OTel dependencies
pip install 'holmesgpt[otel]'

# Or with poetry
poetry install --with otel

# Run with OTel enabled
export OTEL_EXPORTER_OTLP_ENDPOINT="http://your-otel-collector:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_SERVICE_NAME="holmesgpt"
holmes ask "Why is my pod crashing?"
```

### Helm / Kubernetes

Add the following to your Helm `values.yaml`:

```yaml
additionalEnvVars:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.monitoring.svc:4317"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "grpc"
  - name: OTEL_SERVICE_NAME
    value: "holmesgpt"
  # Optional: for backends requiring auth (e.g., Dynatrace, Grafana Cloud)
  - name: OTEL_EXPORTER_OTLP_HEADERS
    value: "Authorization=Api-Token YOUR_TOKEN"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint (enables OTel when set) | *(unset — OTel disabled)* |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Export protocol (`grpc` or `http/protobuf`) | `grpc` |
| `OTEL_SERVICE_NAME` | Service name in traces/metrics | `holmesgpt` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Headers for OTLP exporter (e.g., auth tokens) | *(none)* |

When `OTEL_EXPORTER_OTLP_ENDPOINT` is **not** set, HolmesGPT uses a no-op `DummyTracer` with zero overhead.

## Distributed Traces

Every investigation produces a trace hierarchy:

```
holmesgpt.investigation (root span)
├── gen_ai.chat (per LLM iteration — includes token counts)
│   └── POST (auto-instrumented httpx → LLM provider)
├── holmesgpt.tool.<name> (per tool/MCP call)
│   └── POST (auto-instrumented httpx → MCP server)
│       └── MCP server spans (execute_tool, k8s.api/*, etc.)
├── gen_ai.chat (next iteration)
│   └── ...
└── gen_ai.chat (final answer)
```

### Span Attributes

**Investigation span** (`holmesgpt.investigation`):
- `holmesgpt.investigation.question` — the user's question
- `holmesgpt.investigation.stream` — whether streaming was used

**LLM spans** (`gen_ai.chat`):
- `gen_ai.system` — LLM provider (`litellm`)
- `gen_ai.request.model` — model name
- `gen_ai.usage.input_tokens` — prompt tokens for this call
- `gen_ai.usage.output_tokens` — completion tokens for this call
- `gen_ai.usage.total_tokens` — total tokens
- `holmesgpt.iteration` — iteration number (0-based)

**Tool spans** (`holmesgpt.tool.<name>`):
- `holmesgpt.tool.name` — tool name
- `holmesgpt.tool.status` — result status (`success`, `error`)

### MCP Trace Propagation

When HolmesGPT calls MCP tools over HTTP, trace context is automatically propagated via W3C `traceparent` headers (using httpx auto-instrumentation). MCP servers that support OpenTelemetry will create child spans linked to the same trace.

## Metrics

HolmesGPT exports the following OTel metrics via OTLP:

### Token Usage

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Counter | `{token}` | LLM token consumption |

**Attributes:** `gen_ai.request.model`, `gen_ai.system`, `gen_ai.token.type` (`input` or `output`)

### Investigation Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `holmesgpt.investigation.count` | Counter | `{investigation}` | Number of investigations started |
| `holmesgpt.investigation.duration` | Histogram | `s` | End-to-end investigation duration |
| `holmesgpt.investigation.iterations` | Histogram | `{iteration}` | LLM iterations per investigation |

**Attributes:** `gen_ai.request.model`

### LLM Call Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.operation.duration` | Histogram | `s` | Individual LLM call latency |

**Attributes:** `gen_ai.request.model`, `gen_ai.system`

### Tool / MCP Call Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `holmesgpt.tool.call.count` | Counter | `{call}` | Number of tool calls |
| `holmesgpt.tool.call.duration` | Histogram | `s` | Tool call latency |
| `holmesgpt.tool.call.errors` | Counter | `{error}` | Failed tool calls |

**Attributes:** `holmesgpt.tool.name`

## Example: Dynatrace

```yaml
# Helm values.yaml for Dynatrace
additionalEnvVars:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "https://YOUR_ENV.live.dynatrace.com/api/v2/otlp"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "grpc"
  - name: OTEL_SERVICE_NAME
    value: "holmesgpt"
  - name: OTEL_EXPORTER_OTLP_HEADERS
    value: "Authorization=Api-Token YOUR_DT_TOKEN"
```

### Example: OTel Collector (self-hosted)

```yaml
additionalEnvVars:
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.monitoring.svc:4317"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "grpc"
  - name: OTEL_SERVICE_NAME
    value: "holmesgpt"
```

## Architecture

```
┌──────────────┐    OTLP/gRPC     ┌─────────────────┐
│  HolmesGPT   │────────────────→│  OTel Collector   │──→ Backend
│              │                  │  or Direct OTLP   │   (Dynatrace,
│  Traces +    │                  └─────────────────┘    Grafana, etc.)
│  Metrics     │
│              │    W3C traceparent
│  httpx auto- │─────────────────→┌─────────────────┐
│  instrumented│                  │   MCP Servers     │
└──────────────┘                  │  (child spans)    │
                                  └─────────────────┘
```

The OTel SDK exports traces and metrics over OTLP/gRPC to your collector or backend. httpx auto-instrumentation propagates W3C `traceparent` headers to MCP servers and LLM providers, creating connected distributed traces across services.
