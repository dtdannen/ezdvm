# How to run the examples

Note: These examples need environment variables that are expected to be in a `.env` file where ever you are calling
these examples from. Here, we call them from the top level inside `ezdvm/`

## To run the DVMs

```commandline
git clone https://github.com/dtdannen/ezdvm.git
cd ezdvm/
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
```

then run the example like:

```commandline
python examples/dvms/hello_world_dvm.py
```

## To run the send_test_event.py example

This is a python script that sends a DVM request. It's useful to see if your DVM is able to obtain DVM requests.

This script assumes you have a `.env` file with a `TEST_CLIENT_NSEC` hex value of a nostr account nsec, like the following. This can go in the same `.env` file that the example DVMs use.

```text
TEST_CLIENT_NSEC=9999b465746738f48f5ddd3d2a98a0cca8b3706be4d96ac81cca69cc00a6c752
```

then run the example:

```commandline
python send_test_event.py
```
