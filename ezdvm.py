from asyncio import CancelledError

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
from dotenv import load_dotenv
import sys

load_dotenv()


class EZDVM(ABC):

    def __init__(self, kinds=None, nsec_str=None, ephemeral=False):
        # Remove all existing handlers
        logger.remove()

        # Define a custom log format for console output
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )

        # Add a handler for console logging with the custom format
        logger.add(
            sys.stderr,
            format=console_format,
            level="INFO",
            colorize=True
        )

        # Add a handler for file logging
        logger.add(f"{self.__class__.__name__}.log", rotation="500 MB", level="INFO")

        self.logger = logger

        self.keys = self._get_or_generate_keys(nsec_str=nsec_str, ephemeral=ephemeral)
        self.kinds = self._get_or_set_kinds(kinds=kinds, ephemeral=ephemeral)
        self.signer = NostrSigner.keys(self.keys)
        self.client = Client(self.signer)
        self.job_queue = asyncio.Queue()
        self.finished_jobs = {}  # key is DVM Request event id, value is DVM Result event id

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

        if os.getenv(kinds_env_var_name, False) and not ephemeral:
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
        elif not ephemeral:
            # TODO save it into the .env file if it exists
            pass

        return kind_objs

    def add_relay(self, relay):
        asyncio.run(self.client.add_relay(relay))

    async def async_add_relay(self, relay):
        await self.client.add_relay(relay)

    def start(self):
        asyncio.run(self.async_start())

    async def async_start(self):
        self.logger.info("Connecting to relays...")
        await self.client.connect()
        self.logger.info("Successfully connected.")

        self.logger.info(f"Subscribing to kinds {[k.as_u16() for k in self.kinds]}")
        dvm_filter = Filter().kinds(self.kinds).since(Timestamp.now())
        await self.client.subscribe([dvm_filter])
        self.logger.info(f"Successfully subscribed.")

        class NotificationHandler(HandleNotification):
            def __init__(self, ezdvm_instance):
                self.ezdvm_instance = ezdvm_instance
                self.relay_messages_counter = 0
                self.event_counter = 0

            async def handle(self, relay_url: str, subscription_id: str,event: Event):
                self.event_counter += 1
                self.ezdvm_instance.logger.info(f"Received event {self.event_counter}")
                await self.ezdvm_instance.job_queue.put(event)
                self.ezdvm_instance.logger.info(f"Added event id {event.id().to_hex()} to job queue")
                self.ezdvm_instance.logger.info(f"View this DVM Request on DVMDash: https://dvmdash.live/event/{event.id().to_hex()}")

            async def handle_msg(self, relay_url: str, msg: RelayMessage):
                self.relay_messages_counter += 1
                try:
                    # Try to get the message contents only for more concise logging
                    msg_json = json.loads(msg.as_json())
                    self.ezdvm_instance.logger.info(f"Received message {self.relay_messages_counter} from {relay_url}: {msg_json}")
                except Exception as e:
                    # if it fails, just log entire message json
                    self.ezdvm_instance.logger.info(
                        f"Received message {self.relay_messages_counter} from {relay_url}: {msg}")

        process_queue_task = asyncio.create_task(self.process_events_off_queue())

        handler = NotificationHandler(self)
        # Create a task for handle_notifications instead of awaiting it
        handle_notifications_task = asyncio.create_task(
            self.client.handle_notifications(handler)
        )

        try:
            await asyncio.gather(
                self.process_events_off_queue(),
                self.client.handle_notifications(handler)
            )
        except CancelledError:
            self.logger.info("Tasks cancelled, shutting down...")
        except Exception as e:
            self.logger.error(f"An error occurred: {str(e)}")
            self.logger.error(traceback.format_exc())
        finally:
            await self.shutdown()

    async def process_events_off_queue(self):
        while True:
            #logger.info(f"Job Queue has {self.job_queue.qsize()} events")
            try:
                # Wait for the first event or until max_wait_time
                event = await asyncio.wait_for(
                    self.job_queue.get(), timeout=1)

                request_event_id_as_hex = event.id().to_hex()

                if event and request_event_id_as_hex not in self.finished_jobs.keys():
                    self.logger.info(f"Announcing to consumer/user that we are now processing"
                                     f" the event: {request_event_id_as_hex}")
                    processing_msg_event = await self.announce_status_processing(event)
                    self.logger.info(f"Successfully sent 'processing' status event"
                                     f" with id: {processing_msg_event.id().to_hex()}")

                    self.logger.info(f"Starting to work on event {request_event_id_as_hex}")
                    content = await self.do_work(event)
                    self.logger.info(f"Results from do_work() function are: {content}")
                    self.logger.info(f"Broadcasting DVM Result event with the new results...")
                    dvm_result_event = await self.send_dvm_result(event, content)
                    result_event_id_as_hex = dvm_result_event.id().to_hex()
                    self.logger.info(f"Successfully sent DVM Result event with id: {result_event_id_as_hex}")
                    self.logger.info(f"View this DVM Result on "
                                     f"DVMDash: https://dvmdash.live/event/{result_event_id_as_hex}")

                    self.finished_jobs[request_event_id_as_hex] = result_event_id_as_hex
                else:
                    self.logger.info(f"Skipping DVM Request {event.id().to_hex()}, we already did this,"
                                     f" see DVM Result event: {self.finished_jobs[request_event_id_as_hex]}")

            except asyncio.TimeoutError:
                # If no events received within max_wait_time, continue to next iteration
                continue

            await asyncio.sleep(0.0001)

    async def do_work(self, event):
        """
        Main function of the DVM to do its work on the event. This will only be called after the DVM has been paid,
         unless the DVM is free.
        :param event:
        :return:
        """
        raise NotImplementedError("do_work() is not implemented")

    async def send_dvm_result(self, request_event, result_content):
        """
        Sends the result of the do_work() function out to the relays
        :param result_content:
        :return:
        """
        result_event = EventBuilder.job_result(request_event, result_content, millisats=0).to_event(self.keys)
        await self.client.send_event(result_event)
        return result_event

    async def calculate_price(self, event):
        """
        Calculates the price given the event. The price should be in millisats,
        so to require payment of 1 sat, return 1_000.
        :param event:
        :return:
        """
        raise NotImplementedError("calculate_price() is not implemented")

    async def announce_status_processing(self, request_event):
        """
        Broadcasts an event stating that this DVM has started processing the event
        """
        feedback_event = EventBuilder.job_feedback(job_request=request_event,
                                                   status=DataVendingMachineStatus.PROCESSING,
                                                   extra_info=None,
                                                   amount_millisats=0).to_event(self.keys)
        await self.client.send_event(feedback_event)
        return feedback_event

    async def check_paid(self, event):
        """
        Put any custom code here to check if the event was paid, such as checking LNBits,
        checking a lightning a node, etc.
        :param event:
        :return:
        """
        raise NotImplementedError("check_paid() is not implemented")

    async def shutdown(self):
        self.logger.info("Shutting down EZDVM...")
        await self.client.disconnect()
        self.logger.info("Client disconnected")







