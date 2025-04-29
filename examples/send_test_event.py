#!/usr/bin/env python3
# send_test_event.py
import asyncio
import os
import sys
import json
import time
from datetime import timedelta
from nostr_sdk import (
    Keys,
    Event,
    NostrSigner,
    Client,
    EventBuilder,
    Kind,
    Tag,
    Filter,
    LogLevel,
    Metadata,
    Timestamp,
    HandleNotification,
    RelayMessage,
    EventId,
    init_logger,
)
from dotenv import load_dotenv

load_dotenv()
test_client_nsec = os.getenv("TEST_CLIENT_NSEC")  # nsec1… or raw hex

# Initialize logger
init_logger(LogLevel.INFO)

# Constants
MAX_TEST_DURATION = 60  # seconds
RELAY_URL = "wss://relay.dvmdash.live/"


def build_client():
    """
    Build a Client with the keys taken from $TEST_CLIENT_NSEC.
    Works whether the env‑var is a bech32 nsec or a raw 32‑byte hex string.
    """
    # Parse the keys
    keys = Keys.parse(test_client_nsec)

    print(f"Public key : {keys.public_key().to_hex()}")
    print(f"Private key: {keys.secret_key().to_hex()}")

    # Wrap them in a signer
    signer = NostrSigner.keys(keys)

    # Create the client
    return Client(signer)


def format_event(event_json):
    """Format a Nostr event into a more readable format."""
    try:
        event = json.loads(event_json)

        # Extract basic event information
        event_id = event.get("id", "Unknown ID")
        pubkey = event.get("pubkey", "Unknown pubkey")
        created_at = event.get("created_at", 0)
        kind = event.get("kind", 0)

        # Format timestamp
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
        formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Extract tags
        tags = event.get("tags", [])
        formatted_tags = {}

        for tag in tags:
            if len(tag) >= 2:
                tag_name = tag[0]
                tag_value = tag[1]
                if tag_name in formatted_tags:
                    if isinstance(formatted_tags[tag_name], list):
                        formatted_tags[tag_name].append(tag_value)
                    else:
                        formatted_tags[tag_name] = [formatted_tags[tag_name], tag_value]
                else:
                    formatted_tags[tag_name] = tag_value

        # Format content based on kind
        content = event.get("content", "")

        # Handle different kinds of events
        kind_name = {
            0: "Metadata",
            1: "Text Note",
            5: "Deletion",
            6: "Repost",
            7: "Reaction",
            5003: "Text2Vector Request",
            6003: "Vector Embedding Response",
            5050: "LLM Request",
            6050: "LLM Response",
            5055: "Kind Recommender Request",
            6055: "Kind Recommender Response",
            7000: "DVM Processing Status",
        }.get(kind, f"Unknown Kind ({kind})")

        # Format content based on kind
        if kind == 6003:  # Vector embedding
            try:
                vector_data = json.loads(content)
                if isinstance(vector_data, list) and len(vector_data) > 0:
                    if isinstance(vector_data[0], list):  # Multiple vectors
                        content_summary = f"[Vector data: {len(vector_data)} vectors, each with {len(vector_data[0])} dimensions]"
                    else:  # Single vector
                        content_summary = (
                            f"[Vector data: {len(vector_data)} dimensions]"
                        )
                else:
                    content_summary = "[Invalid vector data]"
            except json.JSONDecodeError:
                content_summary = "[Unable to parse vector data]"
        elif kind == 6055:  # Kind recommender response
            content_summary = content
        elif kind == 6050:  # LLM response
            content_summary = content
        elif kind == 7000:  # Processing status
            status = formatted_tags.get("status", "Unknown")
            content_summary = f"Status: {status.upper()}"
            if content:
                content_summary += f" - {content}"
        else:
            # For other kinds, show the content directly if it's not too long
            if len(content) > 100:
                content_summary = content[:97] + "..."
            else:
                content_summary = content

        # Build the formatted output
        output = [
            f"╔══════════════════════════════════════════════════════════════",
            f"║ Event Type: {kind_name} (Kind: {kind})",
            f"║ Created: {formatted_time}",
            f"║ Event ID: {event_id[:8]}...{event_id[-8:]}",
            f"║ Pubkey: {pubkey[:8]}...{pubkey[-8:]}",
        ]

        # Add status prominently if available
        if "status" in formatted_tags:
            status = formatted_tags["status"]
            status_display = f"║ Status: {status.upper()}"
            if status == "success":
                status_display += " ✓"
            elif status == "error":
                status_display += " ✗"
            elif status == "processing":
                status_display += " ⟳"
            output.append(status_display)

        # Add other important tags
        if "model" in formatted_tags:
            output.append(f"║ Model: {formatted_tags['model']}")

        # Add remaining tags
        if formatted_tags:
            output.append("║ Tags:")
            for tag_name, tag_value in formatted_tags.items():
                if tag_name not in ["status", "model"]:  # Skip already displayed tags
                    if isinstance(tag_value, list):
                        output.append(f"║   - {tag_name}: {', '.join(tag_value)}")
                    else:
                        output.append(f"║   - {tag_name}: {tag_value}")

        # Add content
        output.append("║")
        output.append("║ Content:")

        # Format content with proper indentation
        content_lines = content_summary.split("\n")
        for line in content_lines:
            output.append(f"║   {line}")

        output.append("╚══════════════════════════════════════════════════════════════")

        return "\n".join(output)

    except Exception as e:
        return f"Error formatting event: {str(e)}\nRaw event: {event_json}"


class TestResult:
    """Class to store and display test results."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.start_time = time.time()
        self.request_event_id = None
        self.received_7000 = False
        self.received_6003 = False
        self.received_6050 = False
        self.received_6055 = False
        self.time_to_7000 = None
        self.time_to_6003 = None
        self.time_to_6050 = None
        self.time_to_6055 = None
        self.events = []

    def set_request_id(self, event_id: str):
        self.request_event_id = event_id

    def add_event(self, event: Event, current_time: float):
        """Add a received event to the results."""
        event_kind = event.kind().as_u16()
        event_id = event.id().to_hex()

        self.events.append(event)

        if event_kind == 7000:
            self.received_7000 = True
            self.time_to_7000 = current_time - self.start_time
        elif event_kind == 6003:
            self.received_6003 = True
            self.time_to_6003 = current_time - self.start_time
        elif event_kind == 6050:
            self.received_6050 = True
            self.time_to_6050 = current_time - self.start_time
        elif event_kind == 6055:
            self.received_6055 = True
            self.time_to_6055 = current_time - self.start_time

    def is_complete(self):
        """Check if we've received both expected event types."""
        # For text2vector
        if self.received_7000 and self.received_6003:
            return True
        # For LLM
        if self.received_7000 and self.received_6050:
            return True
        # For kind recommender
        if self.received_7000 and self.received_6055:
            return True
        return False

    def format_result(self):
        """Format the test results for display."""
        status = "✅ SUCCESS" if self.is_complete() else "❌ FAILED"

        result = [
            f"=== Test: {self.test_name} - {status} ===",
            f"Request Event ID: {self.request_event_id}",
            f"Received kind 7000 (status): {'✓' if self.received_7000 else '✗'}"
            + (f" (after {self.time_to_7000:.2f}s)" if self.received_7000 else ""),
        ]

        # Add specific response kinds based on what was received
        if self.received_6003 or self.test_name.lower().find("text2vector") >= 0:
            result.append(
                f"Received kind 6003 (embedding): {'✓' if self.received_6003 else '✗'}"
                + (f" (after {self.time_to_6003:.2f}s)" if self.received_6003 else "")
            )

        if self.received_6050 or self.test_name.lower().find("llm") >= 0:
            result.append(
                f"Received kind 6050 (llm response): {'✓' if self.received_6050 else '✗'}"
                + (f" (after {self.time_to_6050:.2f}s)" if self.received_6050 else "")
            )

        if self.received_6055 or self.test_name.lower().find("kind") >= 0:
            result.append(
                f"Received kind 6055 (kind recommender): {'✓' if self.received_6055 else '✗'}"
                + (f" (after {self.time_to_6055:.2f}s)" if self.received_6055 else "")
            )

        result.append(f"Total events received: {len(self.events)}")

        return "\n".join(result)


class NotificationHandler(HandleNotification):
    """Handler for Nostr notifications."""

    def __init__(self, event_id: str, result: TestResult):
        self.event_id = event_id
        self.result = result
        self.job_completed = asyncio.Event()

    async def handle(self, relay_url: str, subscription_id: str, ev: Event):
        event_id_hex = ev.id().to_hex()
        event_kind = ev.kind().as_u16()

        # Check if this event references our request
        is_related = False
        for tag in ev.tags().to_vec():
            tag_vec = tag.as_vec()
            if len(tag_vec) >= 2 and tag_vec[0] == "e":
                if tag_vec[1] == self.event_id:
                    is_related = True
                    print(f"Found related event: {event_id_hex} (Kind: {event_kind})")
                    self.result.add_event(ev, time.time())

                    # If we receive a 6xxx event, signal that the job is completed
                    if event_kind >= 6000 and event_kind < 7000:
                        print(
                            f"Received response event (Kind: {event_kind}), job completed"
                        )
                        self.job_completed.set()

                    break

        if not is_related:
            # Check for other ways it might be related
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "request":
                    try:
                        request_data = json.loads(tag_vec[1])
                        if request_data.get("id") == self.event_id:
                            is_related = True
                            print(
                                f"Found related event via 'request' tag: {event_id_hex}"
                            )
                            self.result.add_event(ev, time.time())

                            # If we receive a 6xxx event, signal that the job is completed
                            if event_kind >= 6000 and event_kind < 7000:
                                print(
                                    f"Received response event (Kind: {event_kind}), job completed"
                                )
                                self.job_completed.set()

                            break
                    except (json.JSONDecodeError, KeyError):
                        pass

    async def handle_msg(self, relay_url: str, msg: RelayMessage):
        if msg.as_enum().is_end_of_stored_events():
            print(f"Received EOSE from {relay_url}")


async def create_text2vector_request():
    """Create a standard text2vector request event builder."""
    texts = ["first sentence", "second sentence"]
    return EventBuilder(Kind(5003), json.dumps(texts, separators=(",", ":"))).tags(
        [Tag.parse(["n", str(len(texts))])]
    )


async def send_and_fetch(
    kind_request: int, kind_response: int, builder: EventBuilder, test_name: str = None
):
    """
    Send an event and fetch related responses using the improved subscription approach.

    Args:
        kind_request: The kind of the request event
        kind_response: The kind of the expected response event
        builder: The EventBuilder for the request event
        test_name: Optional name for the test
    """
    if test_name is None:
        test_name = f"Kind {kind_request} -> {kind_response} Test"

    result = TestResult(test_name)

    # Create a client
    client = build_client()

    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()

    # Set metadata for the client
    await client.set_metadata(Metadata().set_name("SDK test script"))

    # Build and send the event
    print("Sending event...")
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)

    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    print(f"Sent to: {output.success}")
    print(f"Not sent to: {output.failed}")

    # Set up subscription with a 1-hour time window
    print("Setting up subscription with 1-hour time window...")
    one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)
    response_filter = Filter().event(output.id).since(one_hour_ago)
    await client.subscribe(response_filter)

    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))

    # Wait for either job completion or timeout
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    try:
        # Wait for either the job to complete or the timeout to occur
        await asyncio.wait_for(handler.job_completed.wait(), timeout=MAX_TEST_DURATION)
        print("Job completed, received response event")
    except asyncio.TimeoutError:
        print(
            f"Timeout after {MAX_TEST_DURATION} seconds without receiving a response event"
        )

    # Cancel notification handler
    notification_task.cancel()
    try:
        await notification_task
    except asyncio.CancelledError:
        pass

    # Display results
    print(result.format_result())

    # Display received events
    if result.events:
        print("\nReceived Events:")
        for ev in result.events:
            print(format_event(ev.as_json()))

    await client.disconnect()
    return result.events


async def test_5003():
    """Test the text2vector DVM with a simple embedding request."""
    builder = await create_text2vector_request()
    await send_and_fetch(
        kind_request=5003,
        kind_response=6003,
        builder=builder,
        test_name="Text2Vector Test",
    )


async def test_5050_llm():
    """Test the LLM DVM with a conversation."""
    message_json = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me about Nostr DVMs in 2-3 sentences."},
        ]
    }

    builder = EventBuilder(Kind(5050), json.dumps(message_json)).tags(
        [Tag.parse(["t", "temperature", "0.7"]), Tag.parse(["m", "max_tokens", "1000"])]
    )

    await send_and_fetch(
        kind_request=5050, kind_response=6050, builder=builder, test_name="LLM Test"
    )


async def test_5055_kind_recommender():
    """Test the Kind Recommender DVM with a DVM description."""
    # Example query for a DVM that generates embeddings
    query = "A DVM that generates images based on text prompts and another image"

    # Create a simple event with the query as content
    builder = EventBuilder(Kind(5055), query)

    await send_and_fetch(
        kind_request=5055,
        kind_response=6055,
        builder=builder,
        test_name="Kind Recommender Test",
    )


async def find_related_events(event_id: str, kind_response: int):
    """
    Sanity check function to find events related to a specific event ID.
    This function sets up a subscription and looks for events that reference the given event ID.
    """
    print(f"\n=== SANITY CHECK: Looking for events related to {event_id} ===")

    # Create a client
    client = build_client()

    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()

    # Create a test result to track events
    result = TestResult("Sanity Check")
    result.set_request_id(event_id)

    # Set up subscription with a 1-hour time window
    print("Sanity check: Setting up subscription...")
    one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)
    response_filter = Filter().event(EventId.parse(event_id)).since(one_hour_ago)
    await client.subscribe(response_filter)

    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))

    # Wait for either job completion or timeout
    wait_time = MAX_TEST_DURATION
    print(f"Sanity check: Waiting up to {wait_time} seconds for events...")
    try:
        # Wait for either the job to complete or the timeout to occur
        await asyncio.wait_for(handler.job_completed.wait(), timeout=wait_time)
        print("Sanity check: Job completed, received response event")
    except asyncio.TimeoutError:
        print(
            f"Sanity check: Timeout after {wait_time} seconds without receiving a response event"
        )

    # Cancel notification handler
    notification_task.cancel()
    try:
        await notification_task
    except asyncio.CancelledError:
        pass

    # Display results
    if not result.events:
        print("Sanity check: No related events found.")
    else:
        print(f"Sanity check: Found {len(result.events)} related events:")
        for ev in result.events:
            print(format_event(ev.as_json()))

    await client.disconnect()
    print("=== END SANITY CHECK ===\n")


async def run_all_tests():
    """Run all test functions sequentially."""
    print("Running all tests...")
    print("\n=== TEXT2VECTOR TEST ===")
    await test_5003()
    print("\n=== LLM TEST ===")
    await test_5050_llm()
    print("\n=== KIND RECOMMENDER TEST ===")
    await test_5055_kind_recommender()
    print("\n=== ALL TESTS COMPLETED ===")


def print_usage():
    print("Usage: python send_test_event.py [test_name]")
    print("Available tests:")
    print("  text2vector - Test the text2vector DVM")
    print("  llm - Test the LLM DVM")
    print("  kind - Test the Kind Recommender DVM")
    print("  all - Run all tests")
    print("If no test is specified, only the text2vector test will run.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()
        if test_name in ["--help", "-h", "help"]:
            print_usage()
        elif test_name == "text2vector":
            asyncio.run(test_5003())
        elif test_name == "llm":
            asyncio.run(test_5050_llm())
        elif test_name == "kind":
            asyncio.run(test_5055_kind_recommender())
        elif test_name == "all":
            asyncio.run(run_all_tests())
        else:
            print(f"Unknown test: {test_name}")
            print_usage()
    else:
        # Default to running just the text2vector test
        print("No test specified. Running text2vector test by default.")
        print("Use 'python send_test_event.py --help' to see all options.")
        asyncio.run(test_5003())
