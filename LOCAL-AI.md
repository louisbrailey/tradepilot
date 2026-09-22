# Local AI in TradePilot

TradePilot can use an installed model through Ollama on the Mac. This provider works without an OpenAI API key. The iPhone still connects to the private TradePilot gateway; the Mac must be awake and reachable. The model runs on the Mac, not on the iPhone.

## Configuration

The private gateway configuration accepts these additional string fields:

```json
{
  "AI_PROVIDER": "ollama",
  "OLLAMA_MODEL": "qwen3.8-local:latest"
}
```

Merge these fields into the existing private configuration; preserve its token, account configuration, and other settings. Keep that file outside the app source with permissions `600`, then restart the gateway. The value above is an installed local model alias observed on this Mac, not a verified claim about its upstream model version. The observed model metadata identifies the `qwen35` family, 27.3B parameters, GGUF weights, and Q4_K_M quantization.

For the existing OpenAI integration, set `AI_PROVIDER` to `openai` and supply `OPENAI_API_KEY` plus `OPENAI_MODEL`. OpenAI remains the default when `AI_PROVIDER` is absent. Provider selection is explicit; local failures never fall back to OpenAI.

The authenticated setup response includes `ai_provider`, `ai_model`, and `ai_configured`. These describe configuration only. They do not prove the daemon is running, weights can load, or the model has answered a request successfully.

## Data and execution behavior

The gateway uses fixed loopback addresses for `/api/show` and `/api/chat` on port `11434`. It ignores proxy variables and `OLLAMA_HOST`, rejects redirects, and exposes no configurable remote Ollama endpoint. Before sending portfolio or journal context, it checks the model metadata for installed GGUF weights and rejects cloud/upstream model references. It never downloads models automatically. Ollama's [model metadata API](https://docs.ollama.com/api-reference/show-model-details) describes local model details; its [API types](https://github.com/ollama/ollama/blob/main/api/types.go) include upstream model/host fields.

The selected prompt, permitted snapshot fields, optional journal, and requested research context go to that local model. Brokerage credentials, the app access token, and OpenAI credentials are not attached to inference requests. Existing Webull account identifiers and balance details remain excluded from model context. The local Ollama daemon and its model configuration are trusted components of this setup. Ollama also supports disabling cloud features at the daemon level using its documented [local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features); that global setting is not changed automatically because other applications may use Ollama cloud models.

The request supplies the existing JSON schema, disables streaming and thinking output, uses temperature `0`, and supplies no tools. The app continues to validate every proposal independently. A Webull trade proposal must exactly match one explicit user command, populate an editable form, receive a fresh broker preview, and then receive separate confirmation. Local inference does not acquire broker execution capabilities. [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) supports schema-constrained responses.

## Reliability and limits

TradePilot allows 10 seconds for model metadata and 90 seconds for chat inference. These are application-selected limits, not a guarantee of model speed. The request asks for at most 1,600 output tokens and an 8,192-token context, with silent input truncation and context shifting disabled. Oversized context, unavailable weights, invalid output, and timeouts fail without submitting an order. A complete response must report the selected model, a finished generation with reason `stop`, and valid proposal JSON. Tool calls and incomplete output are rejected. The [Ollama chat API](https://docs.ollama.com/api/chat) defines the generation fields; [provider errors](https://docs.ollama.com/api/errors) remain failures rather than triggering a remote retry.

Only one local inference runs per gateway process. A second request fails promptly while the first is busy. The gateway handles independent HTTP requests concurrently so model generation does not hold portfolio, setup, or order-status requests in a single request queue. Large local models may still compete with other Mac applications for memory and processor time.

Twelve focused local-provider tests cover schema requests, metadata checks before context is sent, disabled proxy/redirect behavior, malformed and partial output, wrong models, errors, timeouts, busy inference, configuration, and refusal to use a remote fallback. The full backend suite passed 90 tests at implementation time. Real local-model performance and device behavior require the separate deployment checks; unit tests alone do not establish either.
