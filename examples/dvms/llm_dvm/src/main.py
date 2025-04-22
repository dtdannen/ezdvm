# llm_dvm main.py
import json
from openai import OpenAI
from ezdvm import EZDVM
from nostr_sdk import Event, EventBuilder, Kind, Tag


class LLMDVM(EZDVM):
    kinds = [5050]  # Text generation kind

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=self.kinds)

        try:
            # Initialize connection to LM Studio
            self.openai_client = OpenAI(
                base_url="http://localhost:1234/v1", api_key="lm-studio"
            )
            self.logger.info("Connected to LM Studio API")
        except Exception as e:
            self.logger.error(f"Failed to connect to LM Studio API: {str(e)}")
            raise

    def estimate_tokens(self, text):
        """Rough estimate of tokens based on character count."""
        # Rough estimate: ~4 characters per token for English text
        return len(text) // 4

    def check_token_limit(self, messages, max_tokens=4000):
        """Check if messages exceed token limit."""
        total_text = ""
        for msg in messages:
            total_text += msg.get("content", "")

        estimated_tokens = self.estimate_tokens(total_text)
        return estimated_tokens <= max_tokens, estimated_tokens

    async def do_work(self, event: Event):
        try:
            # Parse the content as JSON
            content_json = json.loads(event.content())

            # Extract messages
            messages = content_json.get("messages", [])
            if not messages:
                return await self.error_reply(event, "No messages found in content")

            # Check if messages exceed token limit
            within_limit, estimated_tokens = self.check_token_limit(messages)
            if not within_limit:
                return await self.error_reply(
                    event,
                    f"Input exceeds maximum token limit of 4000 (estimated: {estimated_tokens})",
                )

            # Extract parameters from tags
            temperature = 0.7  # Default
            max_tokens = 500  # Default
            top_p = 0.9  # Default
            frequency_penalty = 0.0  # Default
            presence_penalty = 0.0  # Default

            # Parse tags to override defaults
            for tag in event.tags().to_vec():
                tag_parts = tag.as_vec()
                if len(tag_parts) >= 3:
                    if tag_parts[0] == "t":
                        temperature = float(tag_parts[2])
                    elif tag_parts[0] == "m":
                        max_tokens = int(tag_parts[2])
                    elif tag_parts[0] == "p":
                        top_p = float(tag_parts[2])
                    elif tag_parts[0] == "f":
                        frequency_penalty = float(tag_parts[2])
                    elif tag_parts[0] == "r":
                        presence_penalty = float(tag_parts[2])

            self.logger.info(
                f"Making LLM API call with parameters: temperature={temperature}, max_tokens={max_tokens}"
            )

            # Make the API call to LM Studio
            completion = self.openai_client.chat.completions.create(
                model="model-identifier",  # This is ignored by LM Studio but required by the API
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
            )

            # Extract the response
            assistant_message = completion.choices[0].message.content

            # Create response event
            builder = EventBuilder(Kind(6050), assistant_message).tags(
                [
                    Tag.parse(["e", event.id().to_hex()]),
                    Tag.parse(["status", "success"]),
                    Tag.parse(["tokens", str(estimated_tokens)]),
                    Tag.parse(["t", "temperature", str(temperature)]),
                    Tag.parse(["m", "max_tokens", str(max_tokens)]),
                    Tag.parse(["p", "top_p", str(top_p)]),
                ]
            )

            resp_event = await builder.sign(self.signer)
            return resp_event

        except json.JSONDecodeError:
            return await self.error_reply(event, "Invalid JSON in content field")
        except Exception as e:
            self.logger.error(f"Error in do_work: {str(e)}")
            return await self.error_reply(event, f"Error: {str(e)}")


if __name__ == "__main__":
    llm_dvm = LLMDVM()
    llm_dvm.add_relay("wss://relay.dvmdash.live/")
    # Uncomment additional relays as needed
    # llm_dvm.add_relay("wss://relay.primal.net")
    # llm_dvm.add_relay("wss://nos.lol")
    # llm_dvm.add_relay("wss://nostr-pub.wellorder.net")
    llm_dvm.start()
