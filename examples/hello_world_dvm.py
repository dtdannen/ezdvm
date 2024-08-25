from ezdvm import EZDVM


class HelloWorldDVM(EZDVM):

    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=[5050])

    async def do_work(self, event):
        return "Hello World!"

    async def calculate_price(self, event):
        return 0

    async def check_paid(self, event):
        return True


if __name__ == "__main__":
    hello_world_dvm = HelloWorldDVM()
    hello_world_dvm.add_relay("wss://relay.damus.io")
    hello_world_dvm.add_relay("wss://relay.primal.net")
    hello_world_dvm.start()