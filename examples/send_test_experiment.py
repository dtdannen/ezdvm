#!/usr/bin/env python3
# send_test_experiment.py
import asyncio
import os
import sys
import json
import time
from datetime import timedelta
from typing import List, Dict, Any, Tuple, Set
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
MAX_TEST_DURATION = 10  # seconds
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
        self.time_to_7000 = None
        self.time_to_6003 = None
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
    
    def is_complete(self):
        """Check if we've received both expected event types."""
        return self.received_7000 and self.received_6003
    
    def format_result(self):
        """Format the test results for display."""
        status = "✅ SUCCESS" if self.is_complete() else "❌ FAILED"
        
        result = [
            f"=== Test: {self.test_name} - {status} ===",
            f"Request Event ID: {self.request_event_id}",
            f"Received kind 7000 (status): {'✓' if self.received_7000 else '✗'}" + 
            (f" (after {self.time_to_7000:.2f}s)" if self.received_7000 else ""),
            f"Received kind 6003 (embedding): {'✓' if self.received_6003 else '✗'}" + 
            (f" (after {self.time_to_6003:.2f}s)" if self.received_6003 else ""),
            f"Total events received: {len(self.events)}",
        ]
        
        return "\n".join(result)


async def create_text2vector_request():
    """Create a standard text2vector request event builder."""
    texts = ["first sentence", "second sentence"]
    return EventBuilder(Kind(5003), json.dumps(texts, separators=(",", ":"))).tags(
        [Tag.parse(["n", str(len(texts))])]
    )


class NotificationHandler(HandleNotification):
    """Handler for Nostr notifications."""
    
    def __init__(self, event_id: str, result: TestResult):
        self.event_id = event_id
        self.result = result
    
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
                            print(f"Found related event via 'request' tag: {event_id_hex}")
                            self.result.add_event(ev, time.time())
                            break
                    except (json.JSONDecodeError, KeyError):
                        pass
    
    async def handle_msg(self, relay_url: str, msg: RelayMessage):
        if msg.as_enum().is_end_of_stored_events():
            print(f"Received EOSE from {relay_url}")


async def test_strategy_1(client: Client):
    """
    Test Strategy 1: Subscribe first, then broadcast
    """
    result = TestResult("Subscribe first, then broadcast")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Get the keys from the client's signer
    keys = Keys.parse(test_client_nsec)
    
    # Build the event to get its ID
    builder = await create_text2vector_request()
    unsigned_event = builder.build(keys.public_key())
    event_id = unsigned_event.id().to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event ID will be: {event_id}")
    
    # Set up subscription FIRST
    print("Setting up subscription before broadcasting...")
    response_filter = Filter().event(EventId.parse(event_id))
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait a moment for subscription to be established
    await asyncio.sleep(1)
    
    # Now broadcast the event
    print("Broadcasting event...")
    output = await client.send_event_builder(builder)
    print(f"Event sent with ID: {output.id.to_hex()}")
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_2(client: Client):
    """
    Test Strategy 2: Subscribe with a longer time window (1 hour back)
    """
    result = TestResult("Subscribe with 1 hour time window")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription with a 1-hour time window
    print("Setting up subscription with 1-hour time window...")
    one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)
    response_filter = Filter().event(output.id).since(one_hour_ago)
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_3(client: Client):
    """
    Test Strategy 3: Subscribe without a .since() call
    """
    result = TestResult("Subscribe without .since()")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription without since
    print("Setting up subscription without .since()...")
    response_filter = Filter().event(output.id)
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_4(client: Client):
    """
    Test Strategy 4: Subscribe with a filter using .until() for future events
    """
    result = TestResult("Subscribe with .until() for future events")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription with until for future events
    print("Setting up subscription with .until() for future events...")
    future_time = Timestamp.from_secs(Timestamp.now().as_secs() + 3600)  # 1 hour in future
    response_filter = Filter().event(output.id).until(future_time)
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_5(client: Client):
    """
    Test Strategy 5: Subscribe with a filter specifically for the event ID
    """
    result = TestResult("Subscribe with filter for event ID only")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription with just the event ID
    print("Setting up subscription with filter for event ID only...")
    response_filter = Filter().event(output.id)
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_6(client: Client):
    """
    Test Strategy 6: Subscribe with a filter for kinds 6003 and 7000 without event ID
    """
    result = TestResult("Subscribe for kinds 6003 and 7000 without event ID")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription for specific kinds
    print("Setting up subscription for kinds 6003 and 7000...")
    response_filter = Filter().kinds([Kind(6003), Kind(7000)])
    await client.subscribe(response_filter)
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def test_strategy_7(client: Client):
    """
    Test Strategy 7: Subscribe with multiple filters in one subscription
    """
    result = TestResult("Subscribe with multiple filters")
    
    # Connect to relay
    await client.add_relay(RELAY_URL)
    await client.connect()
    
    # Build and send the event
    builder = await create_text2vector_request()
    output = await client.send_event_builder(builder)
    event_id = output.id.to_hex()
    result.set_request_id(event_id)
    
    print(f"\n=== Running Test: {result.test_name} ===")
    print(f"Event sent with ID: {event_id}")
    
    # Set up subscription with multiple filters
    print("Setting up subscription with multiple filters...")
    
    # Filter 1: Event ID
    filter1 = Filter().event(output.id)
    
    # Filter 2: Kinds with recent timeframe
    now = Timestamp.now()
    filter2 = Filter().kinds([Kind(6003), Kind(7000)]).since(
        Timestamp.from_secs(now.as_secs() - 60)  # Last minute
    )
    
    # Subscribe with both filters
    await client.subscribe([filter1, filter2])
    
    # Start notification handler
    handler = NotificationHandler(event_id, result)
    notification_task = asyncio.create_task(client.handle_notifications(handler))
    
    # Wait for the test duration
    print(f"Waiting up to {MAX_TEST_DURATION} seconds for responses...")
    await asyncio.sleep(MAX_TEST_DURATION)
    
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
    return result


async def run_all_tests():
    """Run all test strategies and summarize results."""
    all_results = []
    
    # Test Strategy 1
    client = build_client()
    result = await test_strategy_1(client)
    all_results.append(result)
    
    # Test Strategy 2
    client = build_client()
    result = await test_strategy_2(client)
    all_results.append(result)
    
    # Test Strategy 3
    client = build_client()
    result = await test_strategy_3(client)
    all_results.append(result)
    
    # Test Strategy 4
    client = build_client()
    result = await test_strategy_4(client)
    all_results.append(result)
    
    # Test Strategy 5
    client = build_client()
    result = await test_strategy_5(client)
    all_results.append(result)
    
    # Test Strategy 6
    client = build_client()
    result = await test_strategy_6(client)
    all_results.append(result)
    
    # Test Strategy 7
    client = build_client()
    result = await test_strategy_7(client)
    all_results.append(result)
    
    # Print summary
    print("\n=== TEST RESULTS SUMMARY ===")
    for result in all_results:
        status = "✅ SUCCESS" if result.is_complete() else "❌ FAILED"
        print(f"{result.test_name}: {status}")
    
    # Count successful tests
    successful_tests = sum(1 for result in all_results if result.is_complete())
    print(f"\nSuccessful strategies: {successful_tests}/{len(all_results)}")
    
    if successful_tests > 0:
        print("\nSuccessful strategies:")
        for result in all_results:
            if result.is_complete():
                print(f"- {result.test_name}")
                if result.time_to_7000 and result.time_to_6003:
                    print(f"  Time to receive kind 7000: {result.time_to_7000:.2f}s")
                    print(f"  Time to receive kind 6003: {result.time_to_6003:.2f}s")


def print_usage():
    print("Usage: python send_test_experiment.py [test_number]")
    print("Available tests:")
    print("  1 - Subscribe first, then broadcast")
    print("  2 - Subscribe with 1 hour time window")
    print("  3 - Subscribe without .since()")
    print("  4 - Subscribe with .until() for future events")
    print("  5 - Subscribe with filter for event ID only")
    print("  6 - Subscribe for kinds 6003 and 7000 without event ID")
    print("  7 - Subscribe with multiple filters")
    print("  all - Run all tests")
    print("If no test is specified, all tests will run.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_arg = sys.argv[1].lower()
        if test_arg in ["--help", "-h", "help"]:
            print_usage()
        elif test_arg == "1":
            asyncio.run(test_strategy_1(build_client()))
        elif test_arg == "2":
            asyncio.run(test_strategy_2(build_client()))
        elif test_arg == "3":
            asyncio.run(test_strategy_3(build_client()))
        elif test_arg == "4":
            asyncio.run(test_strategy_4(build_client()))
        elif test_arg == "5":
            asyncio.run(test_strategy_5(build_client()))
        elif test_arg == "6":
            asyncio.run(test_strategy_6(build_client()))
        elif test_arg == "7":
            asyncio.run(test_strategy_7(build_client()))
        elif test_arg == "all":
            asyncio.run(run_all_tests())
        else:
            print(f"Unknown test: {test_arg}")
            print_usage()
    else:
        # Default to running all tests
        print("No test specified. Running all tests.")
        print("Use 'python send_test_experiment.py --help' to see all options.")
        asyncio.run(run_all_tests())
