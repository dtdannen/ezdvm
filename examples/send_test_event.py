import asyncio
import os
from datetime import timedelta

from nostr_sdk import (
    Keys,
    NostrSigner,
    Client,
    EventBuilder,
    Kind,
    Tag,
    Filter,
    LogLevel,
    Metadata,
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


async def send_and_fetch(
    kind_request: int, kind_response: int, tag_i: str | None = None
):
    init_logger(LogLevel.INFO)
    client = build_client()

    # Connect to a relay
    await client.add_relay("wss://relay.dvmdash.live/")
    await client.connect()

    # ---- send ---------------------------------------------------------------
    builder = EventBuilder(
        Kind(kind_request), "New test from rust‑nostr Python bindings!"
    )
    if tag_i is not None:
        builder = builder.tags([Tag.parse(["i", tag_i])])

    await client.send_event_builder(builder)
    await client.set_metadata(Metadata().set_name("SDK test script"))

    # ---- fetch --------------------------------------------------------------
    sleep_time = 10
    print(f"Sleeping for {sleep_time}")
    await asyncio.sleep(sleep_time)  # give the DVM some time

    print("Getting events from relays …")
    flt = Filter().kinds([Kind(kind_response), Kind(7000)])
    events = await client.fetch_events(flt, timedelta(seconds=10))

    for ev in events.to_vec():
        print(ev.as_json())


async def test_5050():
    await send_and_fetch(5050, 6050)


async def test_5003():
    await send_and_fetch(
        kind_request=5003,
        kind_response=6003,
        tag_i="I want to make a DVM that takes text as an input and outputs text embeddings",
    )


if __name__ == "__main__":
    asyncio.run(test_5003())
