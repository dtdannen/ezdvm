# LLM DVM (Kind 5050)

This is a Data Vending Machine (DVM) that provides access to Large Language Models (LLMs) through LM Studio. It allows users to send conversation messages and receive AI-generated responses.

## Features

- Supports full conversation history with multiple messages
- Configurable parameters via tags (temperature, max_tokens, etc.)
- Token limit checking to prevent overloading the model
- Detailed response with metadata about the request

## Requirements

- LM Studio running locally on port 1234
- Python 3.8+
- Required packages: `openai`, `ezdvm`, `nostr_sdk`

## Usage

### Starting the DVM

```bash
cd examples/dvms/llm_dvm/src
python main.py
```

### Sending Requests

Requests should be sent as Nostr events with:

- Kind: 5050
- Content: JSON object with a "messages" array
- Optional tags for parameter configuration

Example content format:

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Tell me about Nostr DVMs."},
    {"role": "assistant", "content": "Nostr DVMs are..."},
    {"role": "user", "content": "How can I create one?"}
  ]
}
```

### Parameters

The following parameters can be configured via tags:

| Tag | Parameter | Default | Description |
|-----|-----------|---------|-------------|
| t | temperature | 0.7 | Controls randomness (0.0 to 1.0) |
| m | max_tokens | 500 | Maximum tokens to generate |
| p | top_p | 0.9 | Controls diversity via nucleus sampling |
| f | frequency_penalty | 0.0 | Penalizes repeated tokens |
| r | presence_penalty | 0.0 | Penalizes repeated topics |

Example tags:

```
["t", "temperature", "0.8"]
["m", "max_tokens", "1000"]
```

### Response

The DVM responds with a Kind 6050 event containing:

- Content: The generated text response
- Tags:
  - Reference to the original request event
  - Status (success or error)
  - Token count estimation
  - Parameters used for generation

## Testing

You can test the DVM using the provided test script:

```bash
python examples/send_test_event.py
```

This will send a test request to the DVM and print the response.

## Limitations

- Maximum input size is approximately 4000 tokens (estimated by character count)
- Requires LM Studio to be running locally
- Currently only supports the model configured in LM Studio
