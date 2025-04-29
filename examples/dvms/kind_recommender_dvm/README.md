# Kind Recommender DVM

This DVM helps developers decide whether to reuse an existing kind or create a new one for their DVM. It analyzes the description of a proposed DVM, finds similar existing kinds, and provides a recommendation with detailed reasoning.

## Features

- Fetches kind descriptions from wiki events on relays with a "-d" tag of "kind:5xxx"
- Uses the text2vector DVM (kind 5003) to generate embeddings for semantic similarity analysis
- Uses the LLM DVM (kind 5050) to generate recommendations and explanations
- Provides detailed reasoning for the recommendation
- Suggests a specific kind number to use (either existing or new)

## Usage

### Running the DVM

```bash
# Clone the repository
git clone https://github.com/yourusername/ezdvm.git
cd ezdvm

# Run the DVM
python examples/dvms/kind_recommender_dvm/src/main.py
```

### Docker

```bash
# Build the Docker image
docker build -t kind-recommender-dvm -f examples/dvms/kind_recommender_dvm/Dockerfile examples/dvms/kind_recommender_dvm/

# Run the container
docker run -it kind-recommender-dvm
```

## Input Format

The DVM accepts a text description of the proposed DVM as the content of a kind 5999 event.

Example:
```
"A DVM that generates embeddings from text input"
```

## Output Format

The DVM returns a detailed recommendation as the content of a kind 6999 event, including:

- Whether to reuse an existing kind or create a new one
- The specific kind number to use
- Detailed reasoning for the recommendation
- A user-friendly explanation
- A list of the most similar existing kinds for reference

## Dependencies

This DVM depends on:
- text2vector DVM (kind 5003) for generating embeddings
- LLM DVM (kind 5050) for generating recommendations

Make sure these DVMs are running and accessible on the same relays.

## Configuration

The DVM connects to the following relay by default:
- wss://relay.dvmdash.live/

Additional relays can be uncommented in the main.py file.
