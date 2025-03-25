import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from ezdvm import EZDVM


class HelloWorldDVM(EZDVM):

    kinds = [5050]

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=self.kinds)

        # Initialize the model and tokenizer globally for reuse
        model_path = "/root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0"

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModel.from_pretrained(model_path)
            self.model.eval()  # Set the model to evaluation mode
        except Exception as e:
            raise


def get_embedding(self, text: str) -> list:
    """Generate embedding for text using BGE model"""
    # Tokenize the input text
    encoded_input = self.tokenizer(
        text,
        padding=True,
        truncation=True,
        max_length=512,  # Limit token length
        return_tensors="pt",
    )

    # Generate embeddings
    with torch.no_grad():
        model_output = self.model(**encoded_input)
        # Get the embeddings from the last hidden state
        embeddings = model_output.last_hidden_state[:, 0, :]
        # Normalize the embeddings
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)

    # Convert to numpy array for pgvector
    result = np.array(embeddings[0].tolist())
    return result

    async def do_work(self, event):
        return "Hello World!"


if __name__ == "__main__":
    hello_world_dvm = HelloWorldDVM()
    # hello_world_dvm.add_relay("wss://localhost:8008")
    hello_world_dvm.add_relay("wss://relay.dvmdash.live/")
    # hello_world_dvm.add_relay("wss://relay.primal.net")
    # hello_world_dvm.add_relay("wss://nos.lol")
    # hello_world_dvm.add_relay("wss://nostr-pub.wellorder.net")
    hello_world_dvm.start()
