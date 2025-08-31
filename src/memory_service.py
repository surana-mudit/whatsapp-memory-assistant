import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from pathlib import Path
from .llm_service import llm_service
from datetime import datetime, timedelta
import pytz

load_dotenv()


class MemoryService:
    def __init__(self):
        # Initialize Mem0 client with new MemoryClient API
        try:
            from mem0 import MemoryClient
            mem0_api_key = os.getenv("MEM0_API_KEY")
            mem0_org_id = os.getenv("MEM0_ORG_ID")
            mem0_project_id = os.getenv("MEM0_PROJECT_ID")
            
            if mem0_api_key and mem0_org_id and mem0_project_id:
                self.memory = MemoryClient(
                    api_key=mem0_api_key,
                    org_id=mem0_org_id,
                    project_id=mem0_project_id
                )
            else:
                print("Warning: Mem0 credentials incomplete (need API_KEY, ORG_ID, PROJECT_ID)")
                self.memory = None
        except Exception as e:
            print(f"Warning: Could not initialize Mem0: {e}")
            self.memory = None
    
    def create_text_memory(self, text: str, user_id: str, metadata: Dict = None) -> str:
        """Create memory from text content"""
        if not self.memory:
            print(f"Warning: Mem0 not available, using fallback for text: {text[:50]}...")
            return f"fallback_{hash(text + user_id)}"
            
        try:
            result = self.memory.add(
                messages=[{"role": "user", "content": text}],
                user_id=user_id,
                metadata=metadata or {},
                infer=False,  # Store exact text content without AI interpretation
                output_format="v1.1",  # Use recommended output format
                version="v2"  # Use v2 API version
            )
            
            # Handle response based on API documentation format
            if isinstance(result, list) and len(result) > 0:
                # Direct array response (as per documentation)
                return result[0].get('id', str(result[0]))
            elif isinstance(result, dict) and 'results' in result:
                # SDK might wrap it in results
                results = result['results']
                if isinstance(results, list) and len(results) > 0:
                    return results[0].get('id', str(results[0]))
                else:
                    print(f"Warning: Text memory creation returned empty results for user {user_id}")
                    return f"empty_result_{hash(text + user_id)}"
            elif isinstance(result, dict) and 'id' in result:
                # Single object response
                return result['id']
            elif isinstance(result, dict):
                return result.get('id', str(result))
            else:
                return str(result)
                
        except Exception as e:
            print(f"Error creating text memory: {e}")
            return f"error_{hash(text + user_id)}"
    
    def create_image_memory(self, image_path: str, user_id: str, metadata: Dict = None) -> Dict[str, str]:
        """Create memory from image by converting to descriptive text
        
        Returns:
            Dict containing 'memory_id' and 'memory_content'
        """
        if not self.memory:
            print(f"Warning: Mem0 not available, using fallback for image: {image_path}")
            return {
                "memory_id": f"fallback_{hash(image_path + user_id)}",
                "memory_content": f"Image file: {Path(image_path).name}"
            }
            
        try:
            # Use combined LLM analysis for efficiency
            analysis_result = llm_service.analyze_image_with_content_insights(image_path)
            image_description = analysis_result.get("description", f"User shared an image file located at {image_path}")
            
            # Prepare the content for Mem0
            content_message = f"I shared an image showing: {image_description}"
            
            # Prepare metadata with nested insights structure (consistent with audio)
            insights = {
                "tags": analysis_result.get("tags", []),
                "category": analysis_result.get("category", "general"),
                "sentiment": analysis_result.get("sentiment", "neutral")
            }
            
            final_metadata = {
                **(metadata or {}), 
                "content_type": "image",
                "file_path": image_path,
                "image_description": image_description,
                "insights": insights
            }
            
            # Create memory with exact content storage
            result = self.memory.add(
                messages=[{
                    "role": "user", 
                    "content": content_message,
                }],
                user_id=user_id,
                metadata=final_metadata,
                infer=False,  # Store exact content without AI interpretation
                output_format="v1.1",
                version="v2"
            )
            
            # Handle response format
            if isinstance(result, list) and len(result) > 0:
                memory_obj = result[0]
                memory_id = memory_obj.get('id', str(memory_obj))
                memory_content = memory_obj.get('memory', image_description)
                return {"memory_id": memory_id, "memory_content": memory_content}
                
            elif isinstance(result, dict) and 'results' in result:
                results = result['results']
                if isinstance(results, list) and len(results) > 0:
                    memory_obj = results[0]
                    memory_id = memory_obj.get('id', str(memory_obj))
                    memory_content = memory_obj.get('memory', image_description)
                    return {"memory_id": memory_id, "memory_content": memory_content}
                    
            elif isinstance(result, dict) and 'id' in result:
                memory_id = result['id']
                memory_content = result.get('memory', image_description)
                return {"memory_id": memory_id, "memory_content": memory_content}
            
            # Fallback if no valid response
            return {
                "memory_id": f"empty_result_{hash(image_path + user_id)}",
                "memory_content": image_description
            }
                
        except Exception as e:
            print(f"Error creating image memory: {e}")
            # Fallback: create text memory about the image
            fallback_text = f"User shared an image file located at {image_path}"
            fallback_memory_id = self.create_text_memory(fallback_text, user_id, metadata)
            return {
                "memory_id": fallback_memory_id,
                "memory_content": fallback_text
            }
    
    def create_audio_memory(self, transcript: str, audio_path: str, user_id: str, 
                           metadata: Dict = None) -> str:
        """Create memory from audio transcript"""
        if not self.memory:
            print(f"Warning: Mem0 not available, using fallback for audio: {transcript[:50]}...")
            return f"fallback_{hash(transcript + user_id)}"
            
        try:
            # Create memory from the transcript
            enhanced_content = f"Audio message transcript: {transcript}"
            
            result = self.memory.add(
                messages=[{"role": "user", "content": enhanced_content}],
                user_id=user_id,
                metadata={
                    **(metadata or {}), 
                    "content_type": "audio",
                    "file_path": audio_path,
                    "transcript": transcript
                },
                infer=False,  # Store exact audio transcript without AI interpretation
                output_format="v1.1",  # Use recommended output format
                version="v2"  # Use v2 API version
            )
            
            # Handle response based on API documentation format
            if isinstance(result, list) and len(result) > 0:
                # Direct array response (as per documentation)
                return result[0].get('id', str(result[0]))
            elif isinstance(result, dict) and 'results' in result:
                # SDK might wrap it in results
                results = result['results']
                if isinstance(results, list) and len(results) > 0:
                    return results[0].get('id', str(results[0]))
                else:
                    print(f"Warning: Audio memory creation returned empty results for user {user_id}")
                    return f"empty_result_{hash(transcript + user_id)}"
            elif isinstance(result, dict) and 'id' in result:
                # Single object response
                return result['id']
            elif isinstance(result, dict):
                return result.get('id', str(result))
            else:
                return str(result)
                
        except Exception as e:
            print(f"Error creating audio memory: {e}")
            return f"error_{hash(transcript + user_id)}"
    
    def search_memories(self, query: str, user_id: str, limit: int = 10, time_entities: List[Dict] = None, user_timezone: str = 'UTC') -> List[Dict]:
        """Search memories using natural language query with optional time filtering"""
        if not self.memory:
            print(f"Warning: Mem0 not available, returning empty search results")
            return []
            
        try:
            # Build filters starting with user_id
            filters = {"user_id": user_id}
            
            # Add time filtering if time entities are provided
            if time_entities:
                time_filters = self._build_time_filters(time_entities, user_timezone)
                if time_filters:
                    # Combine user_id and time filters using AND
                    filters = {"AND": [{"user_id": user_id}, time_filters]}
            
            # For Mem0 v2 API, filters are required
            results = self.memory.search(
                query=query,
                filters=filters,
                top_k=limit,
                version="v2",
                output_format="v1.1"
            )
            
            # Normalize the results format
            if isinstance(results, list):
                return results
            elif isinstance(results, dict) and 'results' in results:
                return results['results']
            else:
                return []
                
        except Exception as e:
            error_msg = str(e).lower()
            # Check if it's the specific mem0 API filter error or HTTP errors
            if any(keyword in error_msg for keyword in [
                "filters are required", 
                "400 bad request", 
                "client error '400'",
                "api request failed"
            ]):
                print(f"Mem0 API filter/validation error, falling back to database search: {e}")
                return []  # Return empty results so database search can handle it
            else:
                print(f"Error searching memories: {e}")
                return []
    
    def get_all_memories(self, user_id: str) -> List[Dict]:
        """Get all memories for a user"""
        if not self.memory:
            print(f"Warning: Mem0 not available, returning empty memories list")
            return []
            
        try:
            # Use get_all for v2 API
            results = self.memory.get_all(
                user_id=user_id, 
                version="v2",
                output_format="v1.1"
            )
            
            if isinstance(results, list):
                return results
            elif isinstance(results, dict) and 'results' in results:
                return results['results']
            else:
                return []
                
        except Exception as e:
            print(f"Error getting all memories: {e}")
            # Fallback: try search with empty query
            return self.search_memories("", user_id, limit=100)
    
    def update_memory(self, memory_id: str, new_content: str, user_id: str) -> bool:
        """Update an existing memory"""
        if not self.memory:
            print(f"Warning: Mem0 not available, cannot update memory")
            return False
            
        try:
            result = self.memory.update(
                memory_id=memory_id,
                data=new_content,
                user_id=user_id,
                version="v2",
                output_format="v1.1"
            )
            return True
        except Exception as e:
            print(f"Error updating memory: {e}")
            return False
    
    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a memory"""
        if not self.memory:
            print(f"Warning: Mem0 not available, cannot delete memory")
            return False
            
        try:
            result = self.memory.delete(
                memory_id=memory_id,
                user_id=user_id,
                version="v2",
                output_format="v1.1"
            )
            return True
        except Exception as e:
            print(f"Error deleting memory: {e}")
            return False
    
    def _analyze_image(self, image_path: str) -> Optional[str]:
        """Analyze image and convert to descriptive text using LLM"""
        try:
            # Use LLM service for image analysis
            description = llm_service.analyze_image(image_path)
            return description or f"Image file: {Path(image_path).name}"
            
        except Exception as e:
            print(f"Error analyzing image: {e}")
            return f"Image file: {Path(image_path).name}"
    
    def extract_content_insights(self, content: str, content_type: str, image_description: str = None) -> Dict[str, Any]:
        """Extract insights and tags from content using LLM"""
        try:
            # Use LLM service for content insights
            insights = llm_service.extract_content_insights(content, content_type, image_description)
            
            # Add content type specific tags if not already present
            if content_type == "image" and "visual" not in insights.get("tags", []):
                insights["tags"].append("visual")
            elif content_type == "audio" and "voice" not in insights.get("tags", []):
                insights["tags"].append("voice")
            
            return insights
            
        except Exception as e:
            print(f"Error extracting content insights: {e}")
            # Fallback to basic structure
            return {
                "tags": ["visual" if content_type == "image" else "voice" if content_type == "audio" else "general"],
                "category": "general",
                "sentiment": "neutral"
            }
    
    def _build_time_filters(self, time_entities: List[Dict], user_timezone: str = 'UTC') -> Optional[Dict]:
        """Build mem0 time filters from time entities"""
        if not time_entities:
            return None
            
        try:
            now = datetime.now(pytz.timezone(user_timezone))
            
            # Use the first time entity for filtering
            time_entity = time_entities[0]
            entity_type = time_entity.get('type')
            
            if entity_type == 'today':
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = start_date + timedelta(days=1)
            elif entity_type == 'yesterday':
                end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                start_date = end_date - timedelta(days=1)
            elif entity_type == 'this_week':
                days_since_monday = now.weekday()
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
                end_date = start_date + timedelta(days=7)
            elif entity_type == 'last_week':
                days_since_monday = now.weekday()
                this_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
                start_date = this_week_start - timedelta(days=7)
                end_date = this_week_start
            elif entity_type == 'days_ago':
                days = int(time_entity.get('value', 1))
                end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                start_date = end_date - timedelta(days=days)
            elif entity_type == 'hours_ago':
                hours = int(time_entity.get('value', 1))
                end_date = now
                start_date = end_date - timedelta(hours=hours)
            elif entity_type == 'last_hours':
                hours = int(time_entity.get('value', 1))
                end_date = now
                start_date = end_date - timedelta(hours=hours)
            else:
                # Fallback for unknown time types - last 24 hours
                start_date = now - timedelta(days=1)
                end_date = now
            
            # Convert to ISO format for mem0 API
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()
            
            return {
                "created_at": {
                    "gte": start_iso,
                    "lte": end_iso
                }
            }
            
        except Exception as e:
            print(f"Error building time filters: {e}")
            return None


# Global memory service instance
memory_service = MemoryService()