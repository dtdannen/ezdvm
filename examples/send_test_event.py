import asyncio
import os
from datetime import timedelta
from nostr_sdk import *

from dotenv import load_dotenv

load_dotenv()

test_client_nsec = os.getenv("TEST_CLIENT_NSEC")


async def main():
    # Init logger
    init_logger(LogLevel.INFO)

    # Initialize client without signer
    # client = Client()

    # Or, initialize with Keys signer
    secret_key = SecretKey.from_hex(test_client_nsec)
    signer = Keys(secret_key=secret_key)

    print(f"public key: {signer.public_key().to_hex()}")
    print(f"private key: {signer.secret_key().to_hex()}")

    # Or, initialize with NIP46 signer
    # app_keys = Keys.parse("..")
    # uri = NostrConnectUri.parse("bunker://.. or nostrconnect://..")
    # signer = NostrConnect(uri, app_keys, timedelta(seconds=60), None)

    client = Client(signer)

    # Add relays and connect
    #await client.add_relay("wss://localhost:8008")
    await client.add_relay("wss://relay.damus.io")
    await client.add_relay("wss://relay.primal.net")
    await client.add_relay("wss://nos.lol")
    await client.add_relay("wss://nostr-pub.wellorder.net")
    await client.connect()

    # Send an event using the Nostr Signer
    builder = EventBuilder(kind=Kind(5050), content="New test from rust-nostr Python bindings!", tags=[])
    await client.send_event_builder(builder)
    await client.set_metadata(Metadata().set_name("Testing rust-nostr"))

    # Mine a POW event and sign it with custom keys
    # custom_keys = Keys.generate()
    # print("Mining a POW text note...")
    # event = EventBuilder.text_note("Hello from rust-nostr Python bindings!").pow(20).sign_with_keys(custom_keys)
    # output = await client.send_event(event)
    # print("Event sent:")
    # print(f" hex:    {output.id.to_hex()}")
    # print(f" bech32: {output.id.to_bech32()}")
    # print(f" Successfully sent to:    {output.output.success}")
    # print(f" Failed to send to: {output.output.failed}")

    await asyncio.sleep(2.0)

    # Get events from relays
    print("Getting events from relays...")
    f = Filter().kinds([Kind(6050), Kind(7000)])
    events = await client.fetch_events([f], timedelta(seconds=10))
    for event in events.to_vec():
        print(event.as_json())


if __name__ == '__main__':
    asyncio.run(main())