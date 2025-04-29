# send_test_event.py
import asyncio
import os
import sys
from datetime import timedelta
import json
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


def build_client():
    """
    Build a Client with the keys taken from $TEST_CLIENT_NSEC.
    Works whether the env‑var is a bech32 nsec or a raw 32‑byte hex string.
    """
    # ① Parse the keys
    keys = Keys.parse(test_client_nsec)

    print(f"public key : {keys.public_key().to_hex()}")
    print(f"private key: {keys.secret_key().to_hex()}")

    # ② Wrap them in a signer (required since v0.41)
    signer = NostrSigner.keys(keys)

    # ③ Create the client
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


async def send_and_fetch(kind_request: int, kind_response: int, builder: EventBuilder):
    """
    Send an event and fetch related responses.

    This function:
    1. Sets up a subscription to listen for responses
    2. Sends the event
    3. Waits for responses via subscription
    4. Also fetches responses via fetch_events
    5. Combines and returns all related events

    Args:
        kind_request: The kind of the request event
        kind_response: The kind of the expected response event
        builder: The EventBuilder for the request event
    """
    # Create a client
    keys = Keys.parse(test_client_nsec)
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    # Connect to a relay
    await client.add_relay("wss://relay.dvmdash.live/")
    await client.connect()

    # Set metadata for the client
    await client.set_metadata(Metadata().set_name("SDK test script"))

    # Create a list to store related events found via subscription
    subscription_events = []
    event_received = asyncio.Event()

    # Define a notification handler to process events in real-time
    class NotificationHandler(HandleNotification):
        async def handle(self, relay_url: str, subscription_id: str, ev: Event):
            nonlocal event_received, event_id
            event_id_hex = ev.id().to_hex()
            event_kind = ev.kind().as_u16()
            # print(
            #    f"Received event via subscription from {relay_url} - Kind: {event_kind}, ID: {event_id_hex[:8]}...{event_id_hex[-8:]}"
            # )

            # Check if this event references our request
            is_related = False
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "e":
                    if tag_vec[1] == event_id:
                        is_related = True
                        print(
                            f"Found related event via subscription: {event_id_hex} (Kind: {event_kind})"
                        )
                        subscription_events.append(ev)
                        event_received.set()
                        break

            # If not found via 'e' tag, check for other ways it might be related
            if not is_related:
                # Check for "request" tag (as mentioned in NIP-90)
                for tag in ev.tags().to_vec():
                    tag_vec = tag.as_vec()
                    if len(tag_vec) >= 2 and tag_vec[0] == "request":
                        try:
                            # The request tag might contain the stringified JSON of the original request
                            request_data = json.loads(tag_vec[1])
                            if request_data.get("id") == event_id:
                                is_related = True
                                print(
                                    f"Found related event via 'request' tag: {event_id_hex}"
                                )
                                subscription_events.append(ev)
                                event_received.set()
                                break
                        except (json.JSONDecodeError, KeyError):
                            pass

            if not is_related:
                # Only print unrelated events if they have an 'e' tag
                for tag in ev.tags().to_vec():
                    tag_vec = tag.as_vec()
                    if len(tag_vec) >= 2 and tag_vec[0] == "e":
                        # print(f"Subscription: unrelated event with tag {tag_vec[1]}")
                        break

        async def handle_msg(self, relay_url: str, msg: RelayMessage):
            # Just log the message type
            if msg.as_enum().is_event_msg():
                # print(f"Received EVENT message from {relay_url}")
                pass
            elif msg.as_enum().is_end_of_stored_events():
                print(f"Received EOSE from {relay_url}")

    # First, build the event to get its ID (but don't send it yet)
    print("Building event to get ID...")
    # Create an unsigned event to get its ID
    unsigned_event = builder.build(keys.public_key())
    event_id = unsigned_event.id().to_hex()
    print(f"Event ID will be: {event_id}")

    # Set up a subscription with a wide time window (1 hour)
    print("Setting up subscription for responses...")
    one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)

    # Now send the event
    print("Sending event...")
    output = await client.send_event_builder(builder)
    # Verify the event ID matches what we expected
    if event_id != output.id.to_hex():
        print(f"Warning: Event ID changed from {event_id} to {output.id.to_hex()}")
        event_id = output.id.to_hex()
    print(f"Event sent with ID: {event_id}")
    print(f"Sent to: {output.success}")
    print(f"Not sent to: {output.failed}")

    print("Sleeping a bit before doing subscription")
    await asyncio.sleep(3)

    # Set up a subscription for the response kinds
    print("Setting up subscription for response kinds...")
    # Filter for events of the response kinds
    # response_filter = Filter().kinds([Kind(kind_response), Kind(7000)]).event(output.id)
    response_filter = Filter().event(output.id)
    await client.subscribe(response_filter)

    # Start handling notifications in the background
    notification_task = asyncio.create_task(
        client.handle_notifications(NotificationHandler())
    )

    # Wait for events to arrive via subscription
    wait_time = 20
    print(f"Waiting up to {wait_time} seconds for events via subscription...")
    try:
        await asyncio.wait_for(event_received.wait(), timeout=wait_time)
        print("Event received via subscription!")
    except asyncio.TimeoutError:
        print("No events received via subscription within the timeout period")

    # Cancel the notification handler task
    notification_task.cancel()
    try:
        await notification_task
    except asyncio.CancelledError:
        pass

    # Also try fetch_events with a wide time window
    print("Getting events from relays via fetch_events...")
    # flt = Filter().kinds([Kind(kind_response), Kind(7000)]).event(output.id)
    flt = Filter().event(output.id)
    events = await client.fetch_events(flt, timedelta(seconds=3600))

    events_vec = events.to_vec()
    if not events_vec:
        print("No events received via fetch_events.")
    else:
        print(f"Received {len(events_vec)} events via fetch_events")

        # Process events from fetch_events
        fetch_related_events = []
        for ev in events_vec:
            # Check if this event references our event
            is_related = False
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "e" and tag_vec[1] == event_id:
                    is_related = True
                    print(f"Found related event via fetch: {ev.id().to_hex()}")
                    fetch_related_events.append(ev)
                    break

            # Also check for "request" tag (as mentioned in NIP-90)
            if not is_related:
                for tag in ev.tags().to_vec():
                    tag_vec = tag.as_vec()
                    if len(tag_vec) >= 2 and tag_vec[0] == "request":
                        try:
                            # The request tag might contain the stringified JSON of the original request
                            request_data = json.loads(tag_vec[1])
                            if request_data.get("id") == event_id:
                                is_related = True
                                print(
                                    f"Found related event via 'request' tag: {ev.id().to_hex()}"
                                )
                                break
                        except (json.JSONDecodeError, KeyError):
                            pass

        if not fetch_related_events:
            print("No related events found via fetch_events.")

    # Combine all found events
    all_related_events = []

    # Add subscription events
    for ev in subscription_events:
        event_id_hex = ev.id().to_hex()
        if not any(e.id().to_hex() == event_id_hex for e in all_related_events):
            all_related_events.append(ev)

    # Add fetch events
    if "fetch_related_events" in locals():
        for ev in fetch_related_events:
            event_id_hex = ev.id().to_hex()
            if not any(e.id().to_hex() == event_id_hex for e in all_related_events):
                all_related_events.append(ev)

    # Display results
    if not all_related_events:
        print("No related events received from either subscription or fetch.")
    else:
        print(f"Found {len(all_related_events)} related events in total:")
        for ev in all_related_events:
            print(format_event(ev.as_json()))

    return all_related_events


async def test_5050():
    message = "Hello this is a test"
    builder = EventBuilder(Kind(5050), message)
    await send_and_fetch(5050, 6050, builder)


async def test_5050_llm():
    """Test the LLM DVM with a conversation."""
    message_json = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me about Nostr DVMs in 2-3 sentences."},
        ]
    }

    builder = EventBuilder(Kind(5050), json.dumps(message_json)).tags(
        [Tag.parse(["t", "temperature", "0.7"]), Tag.parse(["m", "max_tokens", "100"])]
    )

    await send_and_fetch(5050, 6050, builder)


async def test_5003():
    """Test the text2vector DVM with a simple embedding request."""
    texts = ["first sentence", "second sentence"]  # ≤10 items
    builder = EventBuilder(Kind(5003), json.dumps(texts, separators=(",", ":"))).tags(
        [Tag.parse(["n", str(len(texts))])]
    )  # optional metadata

    await send_and_fetch(
        kind_request=5003,
        kind_response=6003,
        builder=builder,
    )


async def test_5055_kind_recommender():
    """Test the Kind Recommender DVM with a DVM description."""
    # Example query for a DVM that generates embeddings
    query = "A DVM that generates images based on text prompts and another image"

    # Create a simple event with the query as content
    builder = EventBuilder(Kind(5055), query)

    await send_and_fetch(5055, 6055, builder)


async def find_related_events(event_id: str, kind_response: int):
    """
    Sanity check function to find events related to a specific event ID.
    This function sets up a subscription and looks for events that reference the given event ID.
    """
    print(f"\n=== SANITY CHECK: Looking for events related to {event_id} ===")

    # Get the keys and create a client
    keys = Keys.parse(test_client_nsec)
    signer = NostrSigner.keys(keys)
    client = Client(signer)

    # Connect to a relay
    await client.add_relay("wss://relay.dvmdash.live/")
    await client.connect()

    # Create a list to store related events
    related_events = []
    event_received = asyncio.Event()

    # Define a notification handler
    class NotificationHandler(HandleNotification):
        async def handle(self, relay_url: str, subscription_id: str, ev: Event):
            print(f"Sanity check: Received event via subscription from {relay_url}")

            # Check if this event references our request
            is_related = False
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "e":
                    if tag_vec[1] == event_id:
                        is_related = True
                        print(f"Sanity check: Found related event: {ev.id().to_hex()}")
                        related_events.append(ev)
                        event_received.set()
                        break

            if not is_related:
                print(f"Sanity check: Received unrelated event: {ev.id().to_hex()}")

        async def handle_msg(self, relay_url: str, msg: RelayMessage):
            if msg.as_enum().is_event_msg():
                # print(f"Sanity check: Received EVENT message from {relay_url}")
                pass
            elif msg.as_enum().is_end_of_stored_events():
                # print(f"Sanity check: Received EOSE from {relay_url}")
                pass

    # Set up a subscription with a very wide time window (1 hour)
    print("Sanity check: Setting up subscription...")
    one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)

    # Filter for events of the response kinds
    # response_filter = Filter().kinds([Kind(kind_response), Kind(7000)])
    # ANCHOR: format-parse-hex
    # To Hex and then Parse
    response_filter = Filter().event(EventId.parse(event_id))
    await client.subscribe(response_filter)

    # Start handling notifications
    notification_task = asyncio.create_task(
        client.handle_notifications(NotificationHandler())
    )

    # Wait for events
    wait_time = 20
    print(f"Sanity check: Waiting up to {wait_time} seconds for events...")
    try:
        await asyncio.wait_for(event_received.wait(), timeout=wait_time)
        print("Sanity check: Event received!")
    except asyncio.TimeoutError:
        print("Sanity check: No events received within the timeout period")

    # Cancel the notification handler task
    notification_task.cancel()
    try:
        await notification_task
    except asyncio.CancelledError:
        pass

    # Also try fetch_events with a wide time window
    print("Sanity check: Trying fetch_events...")
    flt = Filter().kinds([Kind(kind_response), Kind(7000)])
    events = await client.fetch_events(flt, timedelta(seconds=3600))

    events_vec = events.to_vec()
    if not events_vec:
        print("Sanity check: No events received via fetch_events.")
    else:
        print(f"Sanity check: Received {len(events_vec)} events via fetch_events")

        # Process events from fetch_events
        fetch_related_events = []
        for ev in events_vec:
            # Check if this event references our event
            is_related = False
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "e" and tag_vec[1] == event_id:
                    is_related = True
                    print(
                        f"Sanity check: Found related event via fetch: {ev.id().to_hex()}"
                    )
                    fetch_related_events.append(ev)
                    break

        if not fetch_related_events:
            print("Sanity check: No related events found via fetch_events.")
        else:
            print(
                f"Sanity check: Found {len(fetch_related_events)} related events via fetch_events"
            )

    # Combine all found events
    all_related_events = []

    # Add subscription events
    for ev in related_events:
        event_id_hex = ev.id().to_hex()
        if not any(e.id().to_hex() == event_id_hex for e in all_related_events):
            all_related_events.append(ev)

    # Add fetch events
    if "fetch_related_events" in locals():
        for ev in fetch_related_events:
            event_id_hex = ev.id().to_hex()
            if not any(e.id().to_hex() == event_id_hex for e in all_related_events):
                all_related_events.append(ev)

    # Display results
    if not all_related_events:
        print("Sanity check: No related events found at all.")
    else:
        print(f"Sanity check: Found {len(all_related_events)} related events in total:")
        for ev in all_related_events:
            print(format_event(ev.as_json()))

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
