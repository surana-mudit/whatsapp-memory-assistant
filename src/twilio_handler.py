import os
from typing import Dict, Optional
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import requests
from dotenv import load_dotenv
from .database import db
from .media_processor import MediaProcessor
from .memory_service import memory_service
from .utils import extract_query_intent

load_dotenv()


class TwilioHandler:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
        
        self.client = Client(self.account_sid, self.auth_token)
        self.media_processor = MediaProcessor()
        
    def get_twilio_auth(self) -> tuple:
        """Get Twilio auth tuple for media downloads"""
        return (self.account_sid, self.auth_token)
    
    def detect_message_type(self, webhook_data: Dict) -> str:
        """Detect message type from webhook data"""
        num_media = int(webhook_data.get('NumMedia', 0))
        
        if num_media > 0:
            # Check media type
            media_content_type = webhook_data.get('MediaContentType0', '')
            if media_content_type.startswith('image/'):
                return 'image'
            elif media_content_type.startswith('audio/'):
                return 'audio'
            else:
                return 'media'  # Generic media
        else:
            return 'text'
    
    def process_webhook_message(self, webhook_data: Dict) -> Dict:
        """Process incoming webhook message"""
        try:
            # Extract basic message info
            from_number = webhook_data.get('From', '')
            to_number = webhook_data.get('To', '')
            message_sid = webhook_data.get('MessageSid', '')
            body = webhook_data.get('Body', '')
            
            # Clean phone numbers (remove whatsapp: prefix)
            clean_from = from_number.replace('whatsapp:', '')
            clean_to = to_number.replace('whatsapp:', '')
            
            # Get or create user
            user_id = db.create_user(
                phone_number=clean_from,
                whatsapp_id=from_number
            )
            
            # Check if message already processed (idempotency)
            existing_interaction = db.get_interaction_by_sid(message_sid)
            if existing_interaction:
                return {
                    "status": "already_processed",
                    "interaction_id": existing_interaction['id'],
                    "user_id": user_id
                }
            
            # Detect message type
            message_type = self.detect_message_type(webhook_data)
            
            # Process based on message type
            if message_type == 'text':
                return self.process_text_message(webhook_data, user_id)
            elif message_type in ['image', 'audio']:
                return self.process_media_message(webhook_data, user_id, message_type)
            else:
                return self.process_generic_media(webhook_data, user_id)
                
        except Exception as e:
            print(f"Error processing webhook message: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def process_text_message(self, webhook_data: Dict, user_id: str) -> Dict:
        """Process text message"""
        message_sid = webhook_data.get('MessageSid', '')
        body = webhook_data.get('Body', '')
        
        # Create interaction record
        interaction_id = db.create_interaction(
            user_id=user_id,
            twilio_message_sid=message_sid,
            message_type='text',
            content=body
        )
        
        # Check for special commands
        if body.lower().strip() in ['/list', 'list']:
            return self.handle_list_command(user_id, interaction_id)
        
        # Create memory from text
        insights = memory_service.extract_content_insights(body, 'text')
        mem0_memory_id = memory_service.create_text_memory(
            text=body,
            user_id=user_id,
            metadata={
                "source": "whatsapp",
                "message_type": "text",
                "insights": insights
            }
        )
        
        # Save memory to database
        if mem0_memory_id:
            db.create_memory(
                user_id=user_id,
                interaction_id=interaction_id,
                mem0_memory_id=mem0_memory_id,
                memory_content=body,
                tags=insights.get("tags", [])
            )
        
        return {
            "status": "processed",
            "message_type": "text",
            "interaction_id": interaction_id,
            "memory_id": mem0_memory_id,
            "response": "Got it! I've saved your message to memory. 📝"
        }
    
    def process_media_message(self, webhook_data: Dict, user_id: str, message_type: str) -> Dict:
        """Process media messages with comprehensive error handling"""
        try:
            return self._process_media_message_impl(webhook_data, user_id, message_type)
        except Exception as e:
            print(f"Error processing media message: {e}")
            return {
                "status": "error",
                "error": str(e),
                "response": f"🔄 I received your {message_type} but encountered an issue. Let me try again."
            }
    
    def _process_media_message_impl(self, webhook_data: Dict, user_id: str, message_type: str) -> Dict:
        """Process image or audio message"""
        message_sid = webhook_data.get('MessageSid', '')
        media_url = webhook_data.get('MediaUrl0', '')
        media_content_type = webhook_data.get('MediaContentType0', '')
        caption = webhook_data.get('Body', '')
        
        # Create interaction record FIRST to avoid holding DB lock during processing
        try:
            interaction_id = db.create_interaction(
                user_id=user_id,
                twilio_message_sid=message_sid,
                message_type=message_type,
                content=caption,
                media_url=media_url,
                media_file_path=None,  # Will update later
                media_content_hash=None,  # Will update later
                transcript=None  # Will update later
            )
        except Exception as e:
            print(f"Error creating interaction: {e}")
            return {
                "status": "error", 
                "error": f"Database error: {str(e)}",
                "response": "❌ Sorry, I encountered a database error. Please try again."
            }
        
        # Now process media file (this can take time)
        media_result = self.media_processor.process_media(
            media_url=media_url,
            message_type=message_type,
            twilio_auth=self.get_twilio_auth(),
            content_type=media_content_type
        )
        
        if media_result.get('error'):
            return {
                "status": "error",
                "error": f"Failed to process {message_type}: {media_result['error']}"
            }
        
        # Update interaction record with processed media info
        try:
            db.update_interaction(
                interaction_id=interaction_id,
                media_file_path=media_result.get('file_path'),
                media_content_hash=media_result.get('content_hash'),
                transcript=media_result.get('transcript')
            )
        except Exception as e:
            print(f"Error updating interaction: {e}")
            # Continue processing even if update fails
        
        if message_type == 'image':
            # Create image memory
            memory_result = memory_service.create_image_memory(
                image_path=media_result['file_path'],
                user_id=user_id,
                metadata={
                    "source": "whatsapp",
                    "message_type": "image",
                    "file_path": media_result['file_path'],
                    "content_hash": media_result['content_hash']
                }
            )
            
            # Extract memory_id and memory_content from result
            mem0_memory_id = memory_result.get('memory_id', '')
            base_memory_content = memory_result.get('memory_content', 'Image shared by user')
            
            # Include caption if provided
            if caption:
                memory_content = f"Image with caption '{caption}': {base_memory_content}"
            else:
                memory_content = base_memory_content
            
            # Set response based on memory creation success
            if (isinstance(mem0_memory_id, str) and 
                not mem0_memory_id.startswith(('fallback_', 'error_', 'empty_result_')) and
                not mem0_memory_id.startswith('{')):
                response_msg = "📸 I've saved your image to memory!"
            else:
                response_msg = "📸 I received your image but had trouble saving it to memory. The image is stored safely."
            
        elif message_type == 'audio':
            transcript = media_result.get('transcript', '')
            
            # Extract insights for audio if transcript is available
            if transcript:
                insights = memory_service.extract_content_insights(transcript, 'audio')
                memory_content = f"Voice message: {transcript}"
            else:
                insights = {"tags": ["voice"], "category": "audio"}
                memory_content = "Voice message (transcript unavailable)"
            
            # Create audio memory
            mem0_memory_id = memory_service.create_audio_memory(
                transcript=transcript,
                audio_path=media_result['file_path'],
                user_id=user_id,
                metadata={
                    "source": "whatsapp",
                    "message_type": "audio",
                    "file_path": media_result['file_path'],
                    "content_hash": media_result['content_hash'],
                    "insights": insights
                }
            )
            
            if transcript:
                response_msg = f"🎤 Got your voice message: \"{transcript[:50]}{'...' if len(transcript) > 50 else ''}\""
            else:
                response_msg = "🎤 I've saved your voice message to memory!"
        
        # Save memory to database - but only if we have a valid memory ID
        if mem0_memory_id and interaction_id:
            # Check if we have a valid memory ID (not an error/empty result)
            is_valid_memory_id = (
                isinstance(mem0_memory_id, str) and 
                not mem0_memory_id.startswith(('fallback_', 'error_', 'empty_result_')) and
                not mem0_memory_id.startswith('{')  # Not a stringified dict
            )
            
            if is_valid_memory_id:
                try:
                    tags = insights.get("tags", []) if message_type == 'audio' and 'insights' in locals() else []
                    db.create_memory(
                        user_id=user_id,
                        interaction_id=interaction_id,
                        mem0_memory_id=mem0_memory_id,
                        memory_content=memory_content,
                        tags=tags
                    )
                except Exception as e:
                    print(f"Error creating memory record: {e}")
            else:
                print(f"Warning: Skipping database storage - invalid memory ID: {mem0_memory_id}")
        
        return {
            "status": "processed",
            "message_type": message_type,
            "interaction_id": interaction_id,
            "memory_id": mem0_memory_id,
            "file_path": media_result['file_path'],
            "transcript": media_result.get('transcript'),
            "response": response_msg
        }
    
    def process_generic_media(self, webhook_data: Dict, user_id: str) -> Dict:
        """Process generic media (fallback)"""
        # Similar to media processing but more generic
        return self.process_media_message(webhook_data, user_id, 'media')
    
    def handle_list_command(self, user_id: str, interaction_id: str) -> Dict:
        """Handle /list command to show all memories"""
        memories = db.get_memories_for_user(user_id, limit=20)
        
        if not memories:
            response = "🗂️ You don't have any memories saved yet. Send me some messages, images, or voice notes!"
        else:
            response = f"🗂️ Your Recent Memories ({len(memories)} total):\n\n"
            for i, memory in enumerate(memories[:10], 1):
                content = memory['memory_content']
                # Truncate long content
                if len(content) > 80:
                    content = content[:80] + "..."
                
                date_str = memory['created_at'][:10]  # Just the date part
                response += f"{i}. {content} ({date_str})\n"
            
            if len(memories) > 10:
                response += f"\n... and {len(memories) - 10} more memories."
        
        return {
            "status": "processed",
            "message_type": "command",
            "interaction_id": interaction_id,
            "response": response
        }
    
    def search_and_respond(self, query: str, user_id: str) -> str:
        """Search memories and create response with timezone-aware filtering"""
        try:
            # Extract query intent and time entities
            query_intent = extract_query_intent(query)
            time_entities = query_intent.get('time_entities', [])
            
            # Get user's timezone from database
            user = db.get_user_by_id(user_id)
            user_timezone = user.get('timezone', 'UTC') if user else 'UTC'
            
            # Get database memories with timezone-aware filtering first
            if time_entities:
                db_memories = db.get_memories_for_user_with_time_filter(user_id, time_entities, user_timezone, limit=50)
                
                # Now try mem0 search with time filtering as well
                print(f"Time-filtered query detected, trying both mem0 and database search for: {[e['type'] for e in time_entities]}")
                try:
                    mem0_results = memory_service.search_memories(
                        query=query, 
                        user_id=user_id, 
                        limit=5,
                        time_entities=time_entities,
                        user_timezone=user_timezone
                    )
                except Exception as e:
                    print(f"Mem0 time-filtered search failed, using database only: {e}")
                    mem0_results = []
            else:
                db_memories = db.get_memories_for_user(user_id, limit=50)
                # For non-time queries, try mem0 search normally
                mem0_results = memory_service.search_memories(query, user_id, limit=5)
            
            # Apply relevance threshold filter to improve result quality (same as API)
            relevance_threshold = 0.5  # Only return memories with score >= 0.5
            filtered_mem0_results = [
                result for result in mem0_results 
                if result.get('score', 0) >= relevance_threshold
            ]
            
            # If no relevant results, return the top result if score >= 0.3 (more lenient)
            if not filtered_mem0_results and mem0_results:
                top_result = max(mem0_results, key=lambda x: x.get('score', 0))
                if top_result.get('score', 0) >= 0.3:
                    filtered_mem0_results = [top_result]
            
            if not filtered_mem0_results and not db_memories:
                if time_entities:
                    return f"🔍 I couldn't find any relevant memories for that time period. Try a different time range or add some memories first!"
                return "🔍 I couldn't find any relevant memories. Try adding some memories first!"
            
            response = f"🔍 Here's what I found for '{query}':\n\n"
            
            if filtered_mem0_results:
                # Find matching DB records for enriched formatting
                for i, result in enumerate(filtered_mem0_results[:3], 1):
                    memory_text = result.get('memory', result.get('content', str(result)))
                    metadata = result.get('metadata', {})
                    
                    # Add content type emoji and source info
                    content_type = metadata.get('content_type', 'text')
                    source = metadata.get('source', '')
                    
                    if content_type == 'image':
                        type_emoji = '📸'
                    elif content_type == 'audio':
                        type_emoji = '🎤'
                    else:
                        type_emoji = '💬'
                    
                    # Find matching DB record for date info
                    memory_id = result.get('id', result.get('memory_id'))
                    db_match = None
                    for db_mem in db_memories:
                        if db_mem['mem0_memory_id'] == memory_id:
                            db_match = db_mem
                            break
                    
                    # Add date/source context
                    if db_match and db_match.get('interaction_date'):
                        date_str = db_match['interaction_date'][:10]  # YYYY-MM-DD
                        source_info = f" ({date_str})"
                    elif source:
                        source_info = f" (from {source})"
                    else:
                        source_info = ""
                    
                    # Add tags if available for extra context
                    tags = []
                    if 'insights' in metadata and 'tags' in metadata['insights']:
                        tags = metadata['insights']['tags']
                    elif 'tags' in metadata:
                        tags = metadata['tags']
                    
                    # Format tags nicely
                    tag_info = ""
                    if tags:
                        relevant_tags = [tag for tag in tags[:3] if tag not in ['general', 'text', 'voice', 'visual']]  # Skip generic tags
                        if relevant_tags:
                            tag_info = f"\n   🏷️ Tags: {', '.join(relevant_tags)}"
                    
                    # Don't truncate - show full memory text
                    # Just clean up any extra whitespace
                    memory_text = memory_text.strip()
                    
                    response += f"{i}. {type_emoji} {memory_text}{source_info}{tag_info}\n\n"
            
            if len(filtered_mem0_results) == 0 and db_memories:
                # Fallback to filtered database memories
                if time_entities:
                    response_prefix = "🔍 Here are your memories from that time period:\n\n"
                else:
                    response_prefix = "🔍 Here are some recent memories:\n\n"
                response = response_prefix
                for i, memory in enumerate(db_memories[:5], 1):  # Show more results when relying on DB only
                    content = memory['memory_content']
                    if len(content) > 100:
                        content = content[:100] + "..."
                    response += f"{i}. {content}\n"
            
            return response
            
        except Exception as e:
            print(f"Error searching memories: {e}")
            return "❌ Sorry, I had trouble searching your memories. Please try again."
    
    def send_whatsapp_message(self, to_number: str, message: str) -> bool:
        """Send WhatsApp message via Twilio"""
        try:
            message = self.client.messages.create(
                body=message,
                from_=self.whatsapp_number,
                to=to_number
            )
            return True
        except Exception as e:
            print(f"Error sending WhatsApp message: {e}")
            return False
    
    def create_twiml_response(self, message: str) -> str:
        """Create TwiML response"""
        response = MessagingResponse()
        response.message(message)
        return str(response)


# Global handler instance
twilio_handler = TwilioHandler()