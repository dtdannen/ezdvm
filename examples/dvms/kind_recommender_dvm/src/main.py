# kind_recommender_dvm main.py
import json
import asyncio
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
import sys
import os
import time
from dotenv import load_dotenv

from ezdvm import EZDVM
from nostr_sdk import (
    Event,
    EventBuilder,
    Kind,
    Tag,
    Client,
    Keys,
    NostrSigner,
    Filter,
    Timestamp,
    HandleNotification,
    RelayMessage,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("kind_recommender_dvm")

# Load environment variables
load_dotenv()

# Constants
MAX_BATCH = 10  # safety guard for text2vector DVM
DEFAULT_KIND = 5055  # Default kind for this DVM


class KindRecommenderDVM(EZDVM):
    kinds = [5055]  # Using kind 5055 for this DVM, can be changed

    def __init__(self):
        # Choose the job request kinds you will listen and respond to
        # disable nostr_sdk logging and truncate long event content to prevent cluttering logs
        super().__init__(kinds=self.kinds, nostr_sdk_log_level=None, log_full_events=False)
        self.kind_descriptions = {}
        self.embeddings = None
        self.client_keys = None
        self.client_signer = None
        self.client = None

        # Initialize the client for making requests to other DVMs
        self._init_client()

    def _init_client(self):
        """Initialize a client for making requests to other DVMs"""
        # Generate keys for the client if not provided
        self.client_keys = Keys.generate()
        self.client_signer = NostrSigner.keys(self.client_keys)
        self.client = Client(self.client_signer)

        # Add relays
        asyncio.run(self.client.add_relay("wss://relay.dvmdash.live/"))
        asyncio.run(self.client.connect())
        self.logger.info("Client initialized and connected to relays")

    async def fetch_kind_descriptions(self):
        """
        Fetch kind descriptions from wiki events on relays with a -d tag of "kind:5xxx"
        """
        self.logger.info("Fetching kind descriptions from relays...")

        # Create a filter for wiki events with -d tag containing "kind:5"
        wiki_filter = Filter().kinds([Kind(30023)]).limit(100)

        # Fetch events
        events = await self.client.fetch_events(wiki_filter, timedelta(seconds=10))

        # Process events to extract kind descriptions
        kind_descriptions = {}
        for event in events.to_vec():
            # Check tags for -d tag with kind:5xxx
            for tag in event.tags().to_vec():
                tag_parts = tag.as_vec()
                if (
                    len(tag_parts) >= 2
                    and tag_parts[0] == "-d"
                    and "kind:5" in tag_parts[1]
                ):
                    try:
                        # Extract the kind number
                        kind_str = tag_parts[1].split("kind:")[1].split()[0]
                        kind_num = int(kind_str)

                        # Use the event content as the description
                        description = event.content()

                        # Add to our dictionary
                        kind_descriptions[kind_num] = description
                        self.logger.info(f"Found description for kind {kind_num}")
                    except (ValueError, IndexError) as e:
                        self.logger.warning(
                            f"Error parsing kind from tag {tag_parts[1]}: {e}"
                        )

        self.logger.info(f"Fetched {len(kind_descriptions)} kind descriptions")

        # If we didn't find any descriptions, use a fallback
        if not kind_descriptions:
            self.logger.warning("No kind descriptions found, using fallback data")
            kind_descriptions = self._get_fallback_kind_descriptions()

        return kind_descriptions

    def _get_fallback_kind_descriptions(self):
        """
        Provide fallback kind descriptions in case we can't fetch them from relays
        """
        return {
            5000: 'Kind 5000 is a job request to extract text from an input source. The input is typically specified using an "i" tag, which may include a URL or other identifier, and can optionally include parameters like a time range to focus on or the desired text alignment. The output is the extracted text, returned in a specified format such as plain text, markdown, or VTT (Video Text Tracks).',
            5001: "Kind 5001 represents a request to summarize one or more text inputs into a condensed output. The input is provided as one or more tags, each pointing to a Nostr event containing the text to be summarized or the output of a previous DVM job. The output is the summarized text, typically in plain text or Markdown format, with an optional length parameter specifying the desired number of words or paragraphs.",
            5002: "Kind 5002 represents a request to translate text input(s) to a specified language. The input is provided as one or more tags in the event, pointing to the text to be translated. The output is the translated text, typically returned as plain text in the specified target language.",
            5003: "Kind 5003 is a request to generate embeddings from text input. The input is a JSON array of text strings. The output is a JSON array of embedding vectors that represent the semantic meaning of each input text.",
            5050: 'Kind 5050 is a job request to generate text using AI models. The input typically includes a seed sentence or prompt in the "i" tag field for the AI to continue generating from. The output is the generated text, which can be in formats such as plain text or Markdown.',
            5100: 'Kind 5100 is a job request to generate images using AI models. The input includes a prompt provided in the "i" tag field, and optionally a second "i" tag containing a URL to an existing image for alteration. The output is a link to the generated image(s).',
            5999: "Kind 5999 events represent requests made to a Data Vending Machine (DVM) for computational resources. The input for a kind 5999 event includes parameters such as CPU, memory, disk, SSH key, OS image, and OS version, which are specified using tagged data. The output of a kind 5999 event is typically a kind 7000 event that provides feedback on the status of the request, including whether payment is required, an expiration timestamp, and potentially an invoice for payment.",
        }

    class NotificationHandler(HandleNotification):
        """Handler for Nostr notifications."""
        
        def __init__(self, event_id, logger, received_events=None):
            self.event_id = event_id
            self.logger = logger
            self.received_events = received_events if received_events is not None else []
        
        async def handle(self, relay_url, subscription_id, ev):
            event_id_hex = ev.id().to_hex()
            event_kind = ev.kind().as_u16()
            
            # Check if this event references our request
            is_related = False
            for tag in ev.tags().to_vec():
                tag_vec = tag.as_vec()
                if len(tag_vec) >= 2 and tag_vec[0] == "e":
                    if tag_vec[1] == self.event_id:
                        is_related = True
                        self.logger.info(f"Found related event: {event_id_hex} (Kind: {event_kind})")
                        self.received_events.append(ev)
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
                                self.logger.info(f"Found related event via 'request' tag: {event_id_hex}")
                                self.received_events.append(ev)
                                break
                        except (json.JSONDecodeError, KeyError):
                            pass
        
        async def handle_msg(self, relay_url, msg):
            if msg.as_enum().is_end_of_stored_events():
                self.logger.info(f"Received EOSE from {relay_url}")

    async def get_embeddings(self, texts):
        """
        Get embeddings for texts by sending a request to the text2vector DVM

        Args:
            texts: List of text strings to get embeddings for

        Returns:
            numpy.ndarray: Array of embeddings
        """
        self.logger.info(
            f"Getting embeddings for {len(texts)} texts via text2vector DVM"
        )
        self.logger.debug(f"Text samples: {[t[:50] + '...' if len(t) > 50 else t for t in texts[:2]]}")

        # Ensure we don't exceed the maximum batch size
        if len(texts) > MAX_BATCH:
            self.logger.warning(
                f"Too many texts ({len(texts)}), truncating to {MAX_BATCH}"
            )
            texts = texts[:MAX_BATCH]

        # Create a request to the text2vector DVM (kind 5003)
        json_content = json.dumps(texts, separators=(",", ":"))
        self.logger.debug(f"JSON content size: {len(json_content)} bytes")
        
        builder = EventBuilder(
            Kind(5003), json_content
        ).tags([Tag.parse(["n", str(len(texts))])])

        # Send the request
        self.logger.info("Sending request to text2vector DVM...")
        try:
            output = await self.client.send_event_builder(builder)
            request_id = output.id.to_hex()
            self.logger.info(f"Sent embedding request with ID: {request_id}")
        except Exception as e:
            self.logger.error(f"Error sending embedding request: {str(e)}", exc_info=True)
            raise Exception(f"Failed to send embedding request: {str(e)}")

        # Wait for the response using subscription with a 1-hour time window
        self.logger.info("Setting up subscription with 1-hour time window...")
        one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)
        response_filter = Filter().event(output.id).since(one_hour_ago)
        
        try:
            await self.client.subscribe(response_filter)
            
            # Set up notification handler
            received_events = []
            handler = self.NotificationHandler(request_id, self.logger, received_events)
            notification_task = asyncio.create_task(self.client.handle_notifications(handler))
            
            # Wait for response with timeout
            max_wait_time = 60  # seconds - increased from 15 to give more time for response
            self.logger.info(f"Waiting up to {max_wait_time} seconds for responses...")
            
            # Wait and check periodically if we've received any events
            start_time = time.time()
            response_event = None
            
            while time.time() - start_time < max_wait_time:
                await asyncio.sleep(1)  # Check every second
                
                # Look for kind 6003 events in received events
                for ev in received_events:
                    event_kind = ev.kind().as_u16()
                    self.logger.info(f"Checking event with kind: {event_kind}")
                    if event_kind == 6003:
                        response_event = ev
                        self.logger.info(f"Found response event with kind 6003")
                        break
                
                if response_event:
                    break
            
            # Cancel notification handler
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass
            
            # Process the response if we got one
            if response_event:
                response_id = response_event.id().to_hex()
                self.logger.info(f"Received embedding response with ID: {response_id}")
                
                # Check if the response has the expected tags
                tags = response_event.tags().to_vec()
                tag_dict = {}
                for tag in tags:
                    tag_parts = tag.as_vec()
                    if len(tag_parts) >= 2:
                        tag_dict[tag_parts[0]] = tag_parts[1]
                
                self.logger.debug(f"Response tags: {tag_dict}")
                
                # Check status tag
                if "status" in tag_dict and tag_dict["status"] != "success":
                    self.logger.warning(f"Response status is not success: {tag_dict['status']}")
                    raise Exception(f"Text2vector DVM returned status: {tag_dict['status']}")
                
                # Parse the embeddings from the response
                try:
                    content = response_event.content()
                    content_size = len(content)
                    self.logger.info(f"Response content size: {content_size} bytes")
                    
                    if content_size == 0:
                        self.logger.error("Empty response content")
                        raise Exception("Empty response content from text2vector DVM")
                        
                    embeddings = json.loads(content)
                    if not isinstance(embeddings, list):
                        self.logger.error(f"Unexpected embeddings format: {type(embeddings)}")
                        raise Exception(f"Unexpected embeddings format: {type(embeddings)}")
                        
                    self.logger.info(f"Successfully parsed embeddings: shape {len(embeddings)}x{len(embeddings[0]) if embeddings and isinstance(embeddings[0], list) else '?'}")
                    return np.array(embeddings)
                except json.JSONDecodeError as e:
                    self.logger.error(f"JSON decode error: {str(e)}")
                    raise Exception(f"Failed to parse response: {str(e)}")
            else:
                self.logger.error("No response received within the timeout period")
                raise Exception("No response received from text2vector DVM within the timeout period")
                
        except Exception as e:
            self.logger.error(f"Error getting embedding response: {str(e)}", exc_info=True)
            raise Exception(f"Failed to get embedding response: {str(e)}")

    async def generate_llm_response(
        self, prompt, system_prompt=None, temperature=0.7, max_tokens=500
    ):
        """
        Generate a response using the LLM DVM

        Args:
            prompt: The prompt to send to the LLM
            system_prompt: Optional system prompt
            temperature: Temperature parameter for the LLM
            max_tokens: Maximum tokens to generate

        Returns:
            str: The generated text
        """
        self.logger.info("Generating LLM response via LLM DVM")

        # Prepare the messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Create the request content
        content = {"messages": messages}

        # Create a request to the LLM DVM (kind 5050)
        builder = EventBuilder(Kind(5050), json.dumps(content)).tags(
            [
                Tag.parse(["t", "temperature", str(temperature)]),
                Tag.parse(["m", "max_tokens", str(max_tokens)]),
            ]
        )

        # Send the request
        self.logger.info("Sending request to LLM DVM...")
        try:
            output = await self.client.send_event_builder(builder)
            request_id = output.id.to_hex()
            self.logger.info(f"Sent LLM request with ID: {request_id}")
        except Exception as e:
            self.logger.error(f"Error sending LLM request: {str(e)}", exc_info=True)
            raise Exception(f"Failed to send LLM request: {str(e)}")

        # Wait for the response using subscription with a 1-hour time window
        self.logger.info("Setting up subscription with 1-hour time window...")
        one_hour_ago = Timestamp.from_secs(Timestamp.now().as_secs() - 3600)
        response_filter = Filter().event(output.id).since(one_hour_ago)
        
        try:
            await self.client.subscribe(response_filter)
            
            # Set up notification handler
            received_events = []
            handler = self.NotificationHandler(request_id, self.logger, received_events)
            notification_task = asyncio.create_task(self.client.handle_notifications(handler))
            
            # Wait for response with timeout
            max_wait_time = 30  # seconds (longer for LLM responses)
            self.logger.info(f"Waiting up to {max_wait_time} seconds for responses...")
            
            # Wait and check periodically if we've received any events
            start_time = time.time()
            response_event = None
            
            while time.time() - start_time < max_wait_time:
                await asyncio.sleep(1)  # Check every second
                
                # Look for kind 6050 events in received events
                for ev in received_events:
                    if ev.kind().as_u16() == 6050:
                        response_event = ev
                        break
                
                if response_event:
                    break
            
            # Cancel notification handler
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass
            
            # Process the response if we got one
            if response_event:
                response_id = response_event.id().to_hex()
                self.logger.info(f"Received LLM response with ID: {response_id}")
                
                # The content of the response is the generated text
                return response_event.content()
            else:
                self.logger.error("No LLM response received within the timeout period")
                raise Exception("No response received from LLM DVM within the timeout period")
                
        except Exception as e:
            self.logger.error(f"Error getting LLM response: {str(e)}", exc_info=True)
            raise Exception(f"Failed to get LLM response: {str(e)}")

    def search(self, query, embeddings, texts, top_k=10):
        """
        Search for the most similar kind descriptions to the query.

        Args:
            query: The search query
            embeddings: Pre-computed embeddings for the descriptions
            texts: List of texts to search through
            top_k: Number of top results to return

        Returns:
            list: List of tuples (text, similarity_score)
        """
        # Get the embedding for the query
        query_vec = asyncio.run(self.get_embeddings([query]))

        # Calculate similarities
        similarities = cosine_similarity(query_vec, embeddings)[0]

        # Get the top k results
        top_indices = np.argsort(similarities)[::-1][:top_k]

        return [(texts[i], similarities[i]) for i in top_indices]

    def search_kinds(self, query, embeddings, kind_descriptions, top_k=10):
        """
        Search for the most similar kind descriptions to the query.

        Args:
            query: The search query
            embeddings: Pre-computed embeddings for the descriptions
            kind_descriptions: Dictionary mapping kind numbers to descriptions
            top_k: Number of top results to return

        Returns:
            list: List of tuples (kind_number, description, similarity_score)
        """
        # Get the embedding for the query
        query_vec = asyncio.run(self.get_embeddings([query]))

        # Calculate similarities
        similarities = cosine_similarity(query_vec, embeddings)[0]

        # Get the indices of the top k results
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Map indices back to kind numbers and descriptions
        kind_numbers = list(kind_descriptions.keys())
        results = []
        for i in top_indices:
            kind_number = kind_numbers[i]
            description = kind_descriptions[kind_number]
            score = similarities[i]
            results.append((kind_number, description, score))

        return results

    def find_unused_kinds(self, used_kinds, min_kind=5000, max_kind=5999):
        """
        Find unused kind numbers in the specified range.

        Args:
            used_kinds: Set of used kind numbers
            min_kind: Minimum kind number to consider
            max_kind: Maximum kind number to consider

        Returns:
            list: List of unused kind numbers
        """
        all_possible_kinds = set(range(min_kind, max_kind + 1))
        unused_kinds = sorted(list(all_possible_kinds - set(used_kinds)))
        return unused_kinds

    def find_closest_unused_kind(self, target_kind, unused_kinds):
        """
        Find the unused kind number that is closest to the target kind.

        Args:
            target_kind: The target kind number
            unused_kinds: List of unused kind numbers

        Returns:
            int: The closest unused kind number
        """
        if not unused_kinds:
            return None

        # Find the closest unused kind by absolute difference
        closest_kind = min(unused_kinds, key=lambda k: abs(k - target_kind))
        return closest_kind

    async def generate_kind_decision(self, query, similar_kinds):
        """
        Generate a decision on whether to reuse an existing kind or create a new one.

        Args:
            query: The search query describing the new DVM
            similar_kinds: List of tuples (kind_number, description, similarity_score)

        Returns:
            tuple: (reuse_existing, kind_to_use, reasoning)
        """
        # Format the similar kinds for the prompt
        similar_kinds_text = ""
        for i, (kind, description, score) in enumerate(similar_kinds[:3]):
            similar_kinds_text += (
                f"Kind {kind} (similarity: {score:.2f}): {description}\n\n"
            )

        # System prompt
        system_prompt = "You are an expert on Nostr Data Vending Machines (DVMs) and their kind numbers."

        # User prompt
        user_prompt = f"""A developer wants to create a new DVM with this description:
"{query}"

Here are the most similar existing DVM kinds:
{similar_kinds_text}

GUIDELINES FOR REUSING VS. CREATING NEW KINDS:

STRICT CRITERIA:
- CREATE A NEW KIND if the input representation OR output representation differs from existing kinds
- REUSE AN EXISTING KIND if BOTH the input representation AND output representation match an existing kind

Additional considerations:
- Input representation refers to the format, structure, and type of data the DVM accepts
- Output representation refers to the format, structure, and type of data the DVM produces
- Different output data types ALWAYS require a new kind (e.g., text vs. embeddings vs. images vs. JSON)
- Different output formats ALWAYS require a new kind (e.g., plain text vs. vector/matrix vs. URL)
- Functional similarity is NOT sufficient for reuse if the output representation differs
- Minor variations in parameters or optional fields are acceptable for reuse
- Fundamental changes to data structure or format require a new kind

Examples of different output representations requiring new kinds:
- Text summaries vs. vector embeddings (even though both process text, they produce different outputs)
- Images vs. URLs to images (different data types)
- Plain text vs. JSON (different formats)

Based on these guidelines, analyze whether the developer should:
1. Reuse one of the existing kinds above, OR
2. Create a new kind number

First, analyze the input types, output types, and core functionality of both the proposed DVM and the existing kinds.
Then make a clear recommendation with detailed reasoning.

Your response must be in this exact format:
DECISION: [REUSE or NEW]
KIND: [kind number to use - either existing or recommended new one]
REASONING: [detailed explanation of your decision, analyzing input/output similarities and differences]
"""

        # Get the LLM response
        result = await self.generate_llm_response(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,  # Lower temperature for more consistent reasoning
            max_tokens=1000,
        )

        # Parse the response
        lines = result.split("\n")
        decision_line = next(
            (line for line in lines if line.startswith("DECISION:")), ""
        )
        kind_line = next((line for line in lines if line.startswith("KIND:")), "")

        if not decision_line or not kind_line:
            self.logger.error(f"Failed to parse LLM response: {result}")
            return False, 0, "Error: Failed to parse LLM response"

        decision = decision_line.replace("DECISION:", "").strip()
        try:
            kind = int(kind_line.replace("KIND:", "").strip())
        except ValueError:
            self.logger.error(f"Failed to parse kind number from: {kind_line}")
            kind = 0

        # Extract reasoning (everything after KIND: line)
        reasoning_start = lines.index(kind_line) + 1
        reasoning = "\n".join(lines[reasoning_start:]).strip()
        if reasoning.startswith("REASONING:"):
            reasoning = reasoning.replace("REASONING:", "", 1).strip()

        return (decision.upper() == "REUSE"), kind, reasoning

    async def generate_kind_explanation(
        self, query, reuse_existing, kind_to_use, reasoning, similar_kinds
    ):
        """
        Generate a user-friendly explanation.

        Args:
            query: The search query describing the new DVM
            reuse_existing: Boolean indicating whether to reuse an existing kind
            kind_to_use: The kind number to use (either existing or new)
            reasoning: The reasoning behind the decision
            similar_kinds: List of tuples (kind_number, description, similarity_score)

        Returns:
            str: User-friendly explanation
        """
        # Get the most similar kind for reference
        most_similar_kind, most_similar_desc, _ = similar_kinds[0]

        # System prompt
        system_prompt = "You are a helpful assistant specializing in Nostr Data Vending Machines (DVMs)."

        # User prompt based on decision
        if reuse_existing:
            # Find the description of the kind to reuse
            kind_desc = next(
                (desc for k, desc, _ in similar_kinds if k == kind_to_use),
                "Description not available",
            )

            user_prompt = f"""A developer wants to create a DVM that would: "{query}"

You've analyzed this request and determined they should REUSE existing kind {kind_to_use}.
Kind {kind_to_use} description: "{kind_desc}"

Expert reasoning: {reasoning}

Write a helpful, conversational explanation (3-5 sentences) that:
1. Clearly recommends using the existing kind {kind_to_use}
2. Explains why reusing this kind is appropriate, focusing on input/output similarities
3. Mentions any adaptations they might need to make
4. Emphasizes the benefits of kind reuse (ecosystem standardization, client compatibility)

Your explanation should be informative but friendly, and should help the developer understand why reusing an existing kind is the right choice in this case.
"""
        else:
            user_prompt = f"""A developer wants to create a DVM that would: "{query}"

You've analyzed this request and determined they should create a NEW kind {kind_to_use}.
Most similar existing kind for reference - Kind {most_similar_kind}: "{most_similar_desc}"

Expert reasoning: {reasoning}

Write a helpful, conversational explanation (3-5 sentences) that:
1. Clearly recommends creating a new kind {kind_to_use}
2. Explains why a new kind is needed, focusing on input/output differences
3. Describes how this new kind relates to but differs from kind {most_similar_kind}
4. Suggests how they should document the new kind's input/output format

Your explanation should be informative but friendly, and should help the developer understand why creating a new kind is the right choice in this case.
"""

        # Get the LLM response
        explanation = await self.generate_llm_response(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.7,  # Higher temperature for more creative explanations
            max_tokens=800,
        )

        return explanation

    async def recommend_kind_for_query(self, query, min_kind=5000, max_kind=5999):
        """
        Recommend a kind number for a given query by finding the closest unused kind
        to the most similar existing kind.

        Args:
            query: The search query
            min_kind: Minimum kind number to consider
            max_kind: Maximum kind number to consider

        Returns:
            tuple: (recommended_kind, closest_existing_kind, closest_existing_description, similarity_score)
        """
        try:
            # Get kind descriptions
            self.kind_descriptions = await self.fetch_kind_descriptions()

            # Get embeddings for all descriptions
            descriptions = list(self.kind_descriptions.values())
            self.embeddings = await self.get_embeddings(descriptions)

            # Find unused kinds (for now, we'll assume all kinds in our dictionary are used)
            used_kinds = set(self.kind_descriptions.keys())
            unused_kinds = self.find_unused_kinds(used_kinds, min_kind, max_kind)

            # Search for the most similar kind descriptions
            search_results = self.search_kinds(
                query, self.embeddings, self.kind_descriptions, top_k=5
            )

            # Get the top result
            top_kind, top_description, top_score = search_results[0]
            self.logger.info(
                f"Top search result: Kind {top_kind} with score {top_score:.3f}"
            )

            # Find the closest unused kind
            recommended_kind = self.find_closest_unused_kind(top_kind, unused_kinds)
            self.logger.info(
                f"Recommended unused kind: {recommended_kind} (closest to {top_kind})"
            )

            return (recommended_kind, top_kind, top_description, top_score)

        except Exception as e:
            self.logger.error(f"Error recommending kind: {str(e)}")
            raise e

    async def improved_kind_recommendation(self, query):
        """
        Improved function for recommending kind numbers with better LLM-based decision making.

        Args:
            query: Description of the new DVM type

        Returns:
            str: Recommendation result as a formatted string
        """
        # Get kind descriptions and embeddings
        self.kind_descriptions = await self.fetch_kind_descriptions()
        descriptions = list(self.kind_descriptions.values())
        self.embeddings = await self.get_embeddings(descriptions)

        # Search for similar kinds using embeddings
        search_results = self.search_kinds(
            query, self.embeddings, self.kind_descriptions, top_k=5
        )

        # Print search results
        self.logger.info(f"Top 5 similar kinds for query: '{query}'")
        for kind, description, score in search_results[:5]:
            self.logger.info(f"Kind {kind}: {score:.3f} - {description[:100]}...")

        # Get recommendation for a new kind if needed
        used_kinds = set(self.kind_descriptions.keys())
        unused_kinds = self.find_unused_kinds(used_kinds)
        recommended_kind = self.find_closest_unused_kind(
            search_results[0][0], unused_kinds
        )

        # Use LLM to decide whether to reuse or create new
        self.logger.info("Generating decision using LLM DVM...")
        reuse, kind, reasoning = await self.generate_kind_decision(
            query, search_results
        )

        # If creating new, use the recommended kind from our algorithm
        if not reuse:
            kind = recommended_kind

        # Generate user-friendly explanation
        self.logger.info("Generating explanation using LLM DVM...")
        explanation = await self.generate_kind_explanation(
            query, reuse, kind, reasoning, search_results
        )

        # Format the complete result
        result = f"""
Recommendation for: '{query}'

{'REUSE EXISTING KIND' if reuse else 'CREATE NEW KIND'}: {kind}

Expert Reasoning:
{reasoning}

Explanation for Developer:
{explanation}

=== TOP SIMILAR KINDS FOR REFERENCE ===
"""

        # Add the top similar kinds for reference
        for kind, description, score in search_results[:3]:
            result += (
                f"- Kind {kind} (similarity: {score:.3f}): {description[:100]}...\n"
            )

        return result

    async def do_work(self, event: Event):
        """
        Process a kind recommendation request.

        Args:
            event: The request event

        Returns:
            Event: The response event
        """
        try:
            # Extract the query from the event content
            query = event.content()

            if not query or len(query.strip()) == 0:
                return await self.error_reply(
                    event,
                    "Empty query. Please provide a description of the DVM you want to create.",
                )

            # Generate the recommendation
            recommendation = await self.improved_kind_recommendation(query)

            # Create the response event with kind 6055 (kind recommender response)
            builder = EventBuilder(Kind(6055), recommendation).tags(
                [
                    Tag.parse(["e", event.id().to_hex()]),
                    Tag.parse(["status", "success"]),
                ]
            )

            resp_event = await builder.sign(self.signer)
            return resp_event

        except Exception as e:
            self.logger.error(f"Error in do_work: {str(e)}")
            return await self.error_reply(event, f"Error: {str(e)}")


if __name__ == "__main__":
    kind_recommender_dvm = KindRecommenderDVM()
    kind_recommender_dvm.add_relay("wss://relay.dvmdash.live/")
    # Uncomment additional relays as needed
    # kind_recommender_dvm.add_relay("wss://relay.primal.net")
    # kind_recommender_dvm.add_relay("wss://nos.lol")
    # kind_recommender_dvm.add_relay("wss://nostr-pub.wellorder.net")
    kind_recommender_dvm.start()
