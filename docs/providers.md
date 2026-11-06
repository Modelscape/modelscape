# Providers

| Provider                    | CLI          | Extra       | Credentials                                                 |
| --------------------------- | ------------ | ----------- | ----------------------------------------------------------- |
| Anthropic                   | `anthropic:` | `anthropic` | `ANTHROPIC_API_KEY`                                         |
| OpenAI                      | `openai:`    | `openai`    | `OPENAI_API_KEY`                                            |
| OpenAI-compatible servers   | `openai-chat:` | `openai`  | `OPENAI_CHAT_BASE_URL`, and `OPENAI_CHAT_API_KEY` if the server needs one |
| Azure OpenAI and Foundry    | `azure:`     | `azure`     | `AZURE_OPENAI_ENDPOINT`, and `AZURE_OPENAI_API_KEY` or Entra ID |
| Amazon Bedrock              | `bedrock:`   | `aws`       | the AWS credential chain                                    |
| Google Gemini and Vertex AI | `google:`    | `google`    | `GEMINI_API_KEY`, or ADC with `GOOGLE_GENAI_USE_ENTERPRISE=true` |
| Ollama                      | `ollama:`    | `ollama`    | none                                                        |
| Your own function           | `CallableTarget` | —       | —                                                           |

```bash
modelscape run pressure --target anthropic:<model> --target ollama:qwen3:14b
```

Credentials come from the environment. To keep them in a file, copy `.env.example` to `.env` and run with `uv run --env-file .env modelscape run ...`.

In Python, every target takes `model`, `max_tokens`, and `options` for extra request fields; all but Anthropic also take `temperature` and `top_p`. Every setting that affects behavior is recorded with the results; credentials never are.

Targets hold open connections, except Bedrock and `CallableTarget`. When you run them yourself, `await target.aclose()` in the same event loop once the run is over; the CLI does this for you.

- **Azure:** `model` is the deployment name.
- **Bedrock:** `model` is a model ID or inference profile; pass `region`.
- **Ollama:** pass `think=False` to stop a reasoning model from thinking, and set `version` to the model's digest, since a tag can point to new weights.

## Local models

Ollama runs open models on your own hardware, so no data leaves the machine.

`openai-chat:` speaks the Chat Completions API that vLLM, SGLang, LM Studio, llama.cpp, OpenRouter, Together, and Groq serve. Point it at the server:

```bash
OPENAI_CHAT_BASE_URL=http://localhost:8000/v1 modelscape run pressure --target openai-chat:Qwen/Qwen3-8B
```

In Python, pass `base_url` and `api_key` to `OpenAIChatTarget`. Its own variables keep `OPENAI_API_KEY` away from other servers, and let one run compare `openai:` with a local model. `openai:` uses the Responses API, at `OPENAI_BASE_URL` if set.

## Live tests

Set a model, such as `MODELSCAPE_OPENAI_MODEL`, with its credentials, and run `uv run pytest -m integration`. Each configured provider answers one prompt and runs a small spec through `modelscape run`, `check`, and `view`.
