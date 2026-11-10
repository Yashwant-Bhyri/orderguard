# OrderGuard quickstart

This offline example starts an isolated loopback LocalSim paper receiver, creates a **synthetic WebAuthn signer fixture**, and authorizes one AAPL-only mandate. It submits one in-scope paper buy through the Node SDK, then asks the MCP server to sell AAPL. The receiving service must return HTTP 409 and leave the final ledger unchanged for the denied action.

The signer is synthetic. This is not a real passkey ceremony, brokerage integration, model run, testnet order, or safety guarantee for actions inside an allowed mandate.

## Run

From the repository root, with Node.js 22.13 or newer:

```sh
no_keys() {
  env \
    -u OPENAI_API_KEY \
    -u OPENROUTER_API_KEY \
    -u LIQUID_API_KEY \
    -u TYPESAFE_API_KEY \
    -u DEEPSEEK_API_KEY \
    -u ANTHROPIC_API_KEY \
    -u GOOGLE_API_KEY \
    -u MOONSHOT_API_KEY \
    -u BINANCE_API_KEY \
    -u BINANCE_API_SECRET \
    -u AWS_ACCESS_KEY_ID \
    -u AWS_SECRET_ACCESS_KEY \
    -u GH_TOKEN \
    -u GITHUB_TOKEN \
    -u ORDERGUARD_BEARER_TOKEN \
    -u ORDERGUARD_WITNESS_TOKEN \
    -u ORDERGUARD_AUDIT_KEY \
    -u ASB_SCOPE_PRIVATE_KEY \
    -u HF_TOKEN \
    -u HUGGINGFACEHUB_API_TOKEN \
    -u HUGGING_FACE_HUB_TOKEN \
    -u ORDERGUARD_ENV_FILE \
    -u ORDERGUARD_FUTU_ENV_FILE \
    -u CLAUDE_CODE_MESSAGING_TOKEN \
    -u AZURE_OPENAI_API_KEY \
    -u CEREBRAS_API_KEY \
    -u CLAUDE_CODE_OAUTH_TOKEN \
    -u COHERE_API_KEY \
    -u DASHSCOPE_API_KEY \
    -u DEEPINFRA_API_KEY \
    -u FIREWORKS_API_KEY \
    -u GEMINI_API_KEY \
    -u GOOGLE_APPLICATION_CREDENTIALS \
    -u GOOGLE_GENERATIVE_AI_API_KEY \
    -u GROQ_API_KEY \
    -u GITLAB_TOKEN \
    -u MISTRAL_API_KEY \
    -u NVIDIA_API_KEY \
    -u PERPLEXITY_API_KEY \
    -u REPLICATE_API_TOKEN \
    -u SILICONFLOW_API_KEY \
    -u TOGETHER_API_KEY \
    -u XAI_API_KEY \
    -u AWS_SESSION_TOKEN \
    npm_config_cache="${TMPDIR:-/tmp}/og-release-npm-cache-${PWD##*/}" \
    "$@"
}

no_keys npm ci
no_keys npm run quickstart
no_keys npm test
```

The example does not read `.env` files, use provider credentials, or connect to Futu/Binance. The commands unset provider, cloud, source-control, and OrderGuard credential variables used or commonly injected into developer environments. npm uses a per-checkout cache under `TMPDIR`, outside the repository. It binds the receiver to an ephemeral `127.0.0.1` port, keeps generated local signing material and the paper ledger in a disposable temporary directory, and removes that directory when complete.

Expected output is one JSON line with `state: "pass"`, `model: "none"`, `benign.state: "filled"`, `attack.receiverHttpStatus: 409`, `attack.noLedgerEffect: true`, and `ledgerIntegrityVerified: true`. The order ID is generated per run. Any mismatch exits nonzero.
