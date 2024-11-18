# ezdvm
Easily run any python code behind a DVM on Nostr. Just pick a kind (for basic text-to-text use 5050) and put the code you want to run in the do_work() function. Then run the DVM. 

## Install from pip

```commandline
pip install ezdvm
```

## Install from local repo for development on ezdvm

```commandline
git clone https://github.com/dtdannen/ezdvm.git
cd ezdvm/
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
```

## Create your own DVM

Steps:
1. Choose the job request kind in the init function
2. Run any python code inside the do_work() function. The `event` arg is the original job request from the user, in the form of `nostr-sdk event`, for python examples see here: https://github.com/rust-nostr/nostr/tree/master/bindings/nostr-sdk-ffi/bindings-python/examples

```python
from ezdvm import EZDVM


class HelloWorldDVM(EZDVM):

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=[5050])

    async def do_work(self, event):
        return "Hello World!"


if __name__ == "__main__":
    hello_world_dvm = HelloWorldDVM()
    hello_world_dvm.add_relay("wss://relay.damus.io")
    hello_world_dvm.add_relay("wss://relay.primal.net")
    hello_world_dvm.add_relay("wss://nos.lol")
    hello_world_dvm.add_relay("wss://nostr-pub.wellorder.net")
    hello_world_dvm.start()
```



## Testing

Once it's running on your machine, if you are using kind 5050 you can test it here: https://dvmdash.live/playground/ 

_Note that currently you have to use a NIP-07 extension to login first_ 



