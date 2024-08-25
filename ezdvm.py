from nostr_sdk import (
    Keys,
    Client,
    Filter,
    HandleNotification,
    Timestamp,
    LogLevel,
    NostrSigner,
    Kind,
    Event,
    NostrError,
    RelayMessage,
    EventBuilder,
    DataVendingMachineStatus
)
import os
import json
from abc import ABC, abstractmethod
from loguru import logger
import asyncio
import traceback


class EZDVM(ABC):

    def __init__(self, kinds=None, nsec_str=None, ephemeral=False):
        self.logger = logger
        # this creates a logfile named after the child class's name
        self.logger.add(f"{self.__class__.__name__}.log", rotation="500 MB", level="INFO")

        self.keys = self._get_or_generate_keys(nsec_str=nsec_str, ephemeral=ephemeral)
        self.kinds = self._get_or_set_kinds(kinds=kinds, ephemeral=ephemeral)
        self.signer = NostrSigner.keys(self.keys)
        self.client = Client(self.signer)
        self.job_queue = asyncio.Queue()

    def _get_or_generate_keys(self, nsec_str=None, ephemeral=False):
        """
        Tries to get keys from env variable, then tries to get it from nsec_str arg, finally will generate if needed.
        :param nsec_str:
        :param do_not_save_nsec:
        :return:
        """
        nsec_env_var_name = f"{self.__class__.__name__}_NSEC"
        npub_env_var_name = f"{self.__class__.__name__}_NPUB"
        if os.getenv(nsec_env_var_name, None):
            return Keys.parse(os.getenv(nsec_env_var_name))
        elif nsec_str is not None:
            return Keys.parse(nsec_str)
        else:
            logger.warning(f"{nsec_env_var_name} missing from ENV and so we will generate new keys")
            keys = Keys.generate()

            # by default, save the keys for this DVM into a local .env file
            if not ephemeral:
                # check if .env file exists
                env_file_path = os.path.join(os.getcwd(), '.env')
                if not os.path.exists(env_file_path):
                    # .env file doesn't exist, create it
                    with open(env_file_path, 'w') as env_file:
                        env_file.write(f"{nsec_env_var_name}={keys.secret_key().to_bech32()}\n")
                    logger.info(f"Created .env file and saved {nsec_env_var_name}")
                else:
                    # .env file exists, append to it
                    with open(env_file_path, 'a') as env_file:
                        env_file.write(f"{nsec_env_var_name}={keys.secret_key().to_bech32()}\n")
                        env_file.write(f"{npub_env_var_name}={keys.public_key().to_bech32()}\n")
                    logger.info(f"Appended {nsec_env_var_name} to existing .env file")
            else:
                logger.info(f"Did not save nsec and npub because ephemeral is {ephemeral}")

            return keys

    def _get_or_set_kinds(self, kinds:[int] = None, ephemeral=False):
        kinds_env_var_name = f"{self.__class__.__name__}_KINDS"
        kind_objs = None
        if kinds is None:
            # try to get kinds from env
            if os.getenv(kinds_env_var_name, None):
                try:
                    kind_objs = [Kind(int(k)) for k in os.getenv(kinds_env_var_name).split(',')]
                except Exception as e:
                    self.logger.error(f"ENV key value for"
                                 f" {kinds_env_var_name}={os.getenv(kinds_env_var_name)} is invalid: {str(e)}")
                    raise Exception(e)

        else:
            try:
                kind_objs = [Kind(int(k)) for k in kinds]
            except Exception as e:
                self.logger.error(f"Could not create KIND objects from {kinds}: {str(e)}")
                raise Exception(e)

        if not ephemeral:
            kinds_env_value_str = ','.join([str(int(k.as_u16())) for k in kind_objs])
            # save to the .env file
            # check if .env file exists
            env_file_path = os.path.join(os.getcwd(), '.env')
            if not os.path.exists(env_file_path):
                # .env file doesn't exist, create it
                with open(env_file_path, 'w') as env_file:
                    env_file.write(f"{kinds_env_var_name}={kinds_env_value_str}\n")
                logger.info(f"Created .env file and saved {kinds_env_var_name}")
            else:
                # .env file exists, append to it
                with open(env_file_path, 'a') as env_file:
                    env_file.write(f"{kinds_env_var_name}={kinds_env_value_str}\n")
                logger.info(f"Appended {kinds_env_var_name} to existing .env file")

        return kind_objs

    def add_relay(self, relay):
        asyncio.run(self.client.add_relay(relay))

    async def async_add_relay(self, relay):
        await self.client.add_relay(relay)

    def start(self):
        loop = asyncio.get_event_loop()
        try:
            self.logger.info("Starting EZDVM...")
            loop.run_until_complete(self.async_start())
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received. Shutting down...")
        except Exception as e:
            self.logger.error(f"An error occurred: {str(e)}")
            self.logger.error(traceback.format_exc())
        finally:
            self.logger.info("Closing client connection...")
            loop.run_until_complete(self.client.disconnect())
            self.logger.info("Closing event loop...")
            loop.close()
            self.logger.info("EZDVM shut down successfully.")

    async def async_start(self):
        dvm_filter = Filter().kinds(self.kinds).since(Timestamp.now())
        await self.client.subscribe([dvm_filter])
        await self.client.connect()

        class NotificationHandler(HandleNotification):
            def __init__(self, ezdvm_instance):
                self.ezdvm_instance = ezdvm_instance

            async def handle(self, relay_url: str, subscription_id: str,event: Event):
                self.ezdvm_instance.job_queue.put(event)
                self.ezdvm_instance.logger.info(f"Added event id {event.id} to job queue")

            async def handle_msg(self, relay_url: str, msg: RelayMessage):
                self.ezdvm_instance.logger.info(f"Received message from {relay_url}: {msg}")

        handler = NotificationHandler(self)
        await self.client.handle_notifications(handler)

        while True:
            logger.info(f"Job Queue has {self.job_queue.qsize()} events")
            try:
                # Wait for the first event or until max_wait_time
                event = await asyncio.wait_for(
                    self.job_queue.get(), timeout=1)

                await self.announce_status_processing(event)
                await self.do_work(event)

            except asyncio.TimeoutError:
                # If no events received within max_wait_time, continue to next iteration
                continue

            await asyncio.sleep(0.001)

    async def do_work(self, event):
        """
        Main function of the DVM to do its work on the event. This will only be called after the DVM has been paid,
         unless the DVM is free.
        :param event:
        :return:
        """
        raise NotImplementedError("process_event is not implemented")

    async def calculate_price(self, event):
        """
        Calculates the price given the event. The price should be in millisats,
        so to require payment of 1 sat, return 1_000.
        :param event:
        :return:
        """
        raise NotImplementedError("calculate_price is not implemented")

    async def announce_status_processing(self, request_event):
        """
        Broadcasts an event stating that this DVM has started processing the event
        """
        feedback_event = EventBuilder.job_feedback(job_request=request_event,
                                                   status=DataVendingMachineStatus.PROCESSING).to_event(self.keys)
        await self.client.send_event(feedback_event)

    async def check_paid(self, event):
        """
        Put any custom code here to check if the event was paid, such as checking LNBits,
        checking a lightning a node, etc.
        :param event:
        :return:
        """
        raise NotImplementedError("check_paid is not implemented")







