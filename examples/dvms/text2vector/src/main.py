# text2vector main.py
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from ezdvm import EZDVM
from nostr_sdk import Event, EventBuilder, Kind, Tag
import json

MAX_BATCH = 10  # safety guard


class HelloWorldDVM(EZDVM):

    kinds = [5003]

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=self.kinds)

        # Initialize the model and tokenizer globally for reuse
        # model_path = "/root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0"

        try:
            model_id = "BAAI/bge-large-en-v1.5"
            self.tokenizer = AutoTokenizer.from_pretrained(model_id)
            self.model = AutoModel.from_pretrained(model_id)
            self.model.eval()  # Set the model to evaluation mode
        except Exception as e:
            raise

    def get_embeddings(self, texts: list[str]) -> np.ndarray:
        """Return an (n, d) array of L2‑normalised embeddings."""
        assert 0 < len(texts) <= MAX_BATCH, "up to 10 inputs allowed"

        enc = self.tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )

        with torch.no_grad():
            out = self.model(**enc)
            emb = out.last_hidden_state[:, 0, :]
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)

        return emb.cpu().numpy()  # (n, 1024)

    async def do_work(self, event: Event):
        texts = json.loads(event.content())

        if not texts:
            return await self.error_reply(event, "content must be a JSON list of texts")

        if len(texts) > MAX_BATCH:
            return await self.error_reply(event, f"max {MAX_BATCH} texts")

        # 2. get embeddings
        embeddings = self.get_embeddings(texts)  # (n, 1024) ndarray
        payload = json.dumps(embeddings.tolist(), separators=(",", ":"))

        builder = EventBuilder(Kind(6003), payload).tags(
            [
                Tag.parse(["e", event.id().to_hex()]),
                Tag.parse(["model", "bge-large-en-v1.5"]),
                Tag.parse(["dim", str(embeddings.shape[1])]),
                Tag.parse(["status", "success"]),
            ]
        )
        resp_event = await builder.sign(self.signer)

        return resp_event


if __name__ == "__main__":
    hello_world_dvm = HelloWorldDVM()
    # hello_world_dvm.add_relay("wss://localhost:8008")
    hello_world_dvm.add_relay("wss://relay.dvmdash.live/")
    # hello_world_dvm.add_relay("wss://relay.primal.net")
    # hello_world_dvm.add_relay("wss://nos.lol")
    # hello_world_dvm.add_relay("wss://nostr-pub.wellorder.net")
    hello_world_dvm.start()
