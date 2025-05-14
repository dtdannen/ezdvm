# text2vector main.py
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from ezdvm import EZDVM
from nostr_sdk import Event, EventBuilder, Kind, Tag
import json
import os
import logging
import time

MAX_BATCH = 3  # hard limit based on default event sizes for relays


class TooManyTextsException(Exception):
    pass


class Text2VectorDVM(EZDVM):

    kinds = [5003]

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        # Enable full event logging to see complete tags and event content
        super().__init__(
            kinds=self.kinds, nostr_sdk_log_level=None, log_full_events=True
        )

        # Initialize the model and tokenizer globally for reuse
        # model_path = "/root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0"

        # Initialize the model and tokenizer globally for reuse
        model_path = "/root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0"

        try:
            self.logger.info(f"Loading model from local path: {model_path}")
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModel.from_pretrained(model_path)
            self.model.eval()  # Set the model to evaluation mode
        except Exception as e:
            self.logger.error(f"Error loading model: {str(e)}")
            raise

    def get_embeddings(self, texts: list[str]) -> np.ndarray:
        """Return an (n, d) array of L2‑normalised embeddings."""
        if len(texts) > MAX_BATCH:
            raise TooManyTextsException(
                f"{len(texts)} strings given, limit is {MAX_BATCH}"
            )

        enc = self.tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )

        with torch.no_grad():
            out = self.model(**enc)
            emb = out.last_hidden_state[:, 0, :]
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)

        return emb.cpu().numpy()  # (n, 1024)

    async def do_work(self, event: Event):
        self.logger.info(f"Received embedding request with ID: {event.id().to_hex()}")
        self.logger.info(f"Processing request from pubkey: {event.author().to_hex()}")

        try:
            texts = json.loads(event.content())
            self.logger.info(f"Request contains {len(texts)} text(s) to embed")

            if not texts:
                self.logger.warning("Empty text list received")
                return await self.error_reply(
                    event, "content must be a JSON list of texts"
                )

            if len(texts) > MAX_BATCH:
                self.logger.warning(
                    f"Request exceeds max batch size: {len(texts)} > {MAX_BATCH}"
                )
                return await self.error_reply(event, f"max {MAX_BATCH} texts")

            # Get embeddings
            self.logger.info("Generating embeddings...")
            start_time = time.time()
            embeddings = self.get_embeddings(texts)  # (n, 1024) ndarray
            end_time = time.time()
            self.logger.info(
                f"Embeddings generated in {end_time - start_time:.2f} seconds"
            )
            self.logger.info(f"Embedding shape: {embeddings.shape}")

            # Prepare response
            payload = json.dumps(embeddings.tolist(), separators=(",", ":"))
            self.logger.info(f"Response payload size: {len(payload)} bytes")

            # Build response event
            event_id = event.id().to_hex()
            self.logger.info(f"Creating response for request ID: {event_id}")
            builder = EventBuilder(Kind(6003), payload).tags(
                [
                    Tag.parse(["e", event_id]),
                    Tag.parse(["model", "bge-large-en-v1.5"]),
                    Tag.parse(["dim", str(embeddings.shape[1])]),
                    Tag.parse(["status", "success"]),
                ]
            )
            resp_event = await builder.sign(self.signer)
            self.logger.info(
                f"Response event created with ID: {resp_event.id().to_hex()}"
            )

            return resp_event
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {str(e)}")
            return await self.error_reply(event, f"Invalid JSON: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error processing request: {str(e)}", exc_info=True)
            return await self.error_reply(event, f"Error: {str(e)}")


if __name__ == "__main__":
    text2vector_dvm = Text2VectorDVM()
    # text2vector_dvm.add_relay("wss://localhost:8008")
    text2vector_dvm.add_relay("wss://relay.dvmdash.live/")
    # text2vector_dvm.add_relay("wss://relay.primal.net")
    # text2vector_dvm.add_relay("wss://nos.lol")
    # text2vector_dvm.add_relay("wss://nostr-pub.wellorder.net")
    text2vector_dvm.start()
