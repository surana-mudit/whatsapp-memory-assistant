from fastapi import FastAPI, Request, HTTPException, Query, Form, Body
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse
from typing import Optional
from dotenv import load_dotenv
import uvicorn
from .database import db
from .twilio_handler import twilio_handler
from .memory_service import memory_service
from .utils import extract_query_intent
from datetime import datetime
import json

load_dotenv()

class MemoryCreate(BaseModel):
    content: str
    user_id: str
    content_type: str = "text"
    metadata: Optional[str] = None

app = FastAPI(
    title="WhatsApp Memory Assistant",
    description="A WhatsApp chatbot with intelligent memory capabilities using Mem0",
    version="1.0.0"
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "message": "WhatsApp Memory Assistant is running!",
        "status": "healthy",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": "connected",
            "twilio": "configured",
            "mem0": "configured",
            "elevenlabs": "configured"
        }
    }


@app.post("/webhook")
async def webhook(request: Request):
    """
    Twilio webhook endpoint for receiving WhatsApp messages
    """
    try:
        # Get form data from Twilio webhook
        form_data = await request.form()
        webhook_data = dict(form_data)
        
        print(f"Received webhook: {webhook_data}")
        
        # Check if this is a query or regular message
        body = webhook_data.get('Body', '').strip()
        from_number = webhook_data.get('From', '')
        
        # Get user
        clean_from = from_number.replace('whatsapp:', '')
        user_id = db.create_user(phone_number=clean_from, whatsapp_id=from_number)
        
        # Check if it's a search query (contains question words or ends with ?)
        is_query = (
            body.endswith('?') or 
            any(word in body.lower() for word in ['what', 'when', 'where', 'who', 'how', 'show me', 'find', 'which'])
        ) and body.lower() not in ['/list', 'list']
        
        if is_query:
            # Handle as search query
            response_text = twilio_handler.search_and_respond(body, user_id)
        else:
            # Process as regular message/media
            result = twilio_handler.process_webhook_message(webhook_data)
            if result.get('status') == 'error':
                response_text = result.get('response', f"❌ Error: {result.get('error', 'Unknown error occurred')}")
            else:
                response_text = result.get('response', 'Message processed successfully!')
        
        # Create TwiML response
        twiml_response = twilio_handler.create_twiml_response(response_text)
        return PlainTextResponse(content=twiml_response, media_type="application/xml")
        
    except Exception as e:
        print(f"Webhook error: {e}")
        error_response = twilio_handler.create_twiml_response(
            "❌ Sorry, I encountered an error processing your message. Please try again."
        )
        return PlainTextResponse(content=error_response, media_type="application/xml")


@app.post("/memories")
async def add_memory(memory: MemoryCreate):
    """
    Add a new memory manually
    """
    try:
        # Parse metadata if provided
        parsed_metadata = {}
        if memory.metadata:
            try:
                parsed_metadata = json.loads(memory.metadata)
            except json.JSONDecodeError:
                parsed_metadata = {"raw_metadata": memory.metadata}
        
        # Add source info
        parsed_metadata.update({
            "source": "api",
            "content_type": memory.content_type,
            "timestamp": datetime.now().isoformat()
        })
        
        # Create memory based on type
        if memory.content_type == "text":
            mem0_memory_id = memory_service.create_text_memory(
                text=memory.content,
                user_id=memory.user_id,
                metadata=parsed_metadata
            )
        elif memory.content_type == "image":
            mem0_memory_id = memory_service.create_image_memory(
                image_path=memory.content,  # Assuming content is file path for images
                user_id=memory.user_id,
                metadata=parsed_metadata
            )
        else:
            # Default to text memory
            mem0_memory_id = memory_service.create_text_memory(
                text=memory.content,
                user_id=memory.user_id,
                metadata=parsed_metadata
            )
        
        # Create dummy interaction record for API-created memories
        interaction_id = db.create_interaction(
            user_id=memory.user_id,
            twilio_message_sid=f"api_{datetime.now().timestamp()}",
            message_type=memory.content_type,
            content=memory.content
        )
        
        # Save memory to database
        if mem0_memory_id:
            memory_id = db.create_memory(
                user_id=memory.user_id,
                interaction_id=interaction_id,
                mem0_memory_id=mem0_memory_id,
                memory_content=memory.content,
                tags=parsed_metadata.get("tags", [])
            )
        
        return {
            "status": "success",
            "memory_id": mem0_memory_id,
            "db_memory_id": memory_id,
            "message": "Memory created successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating memory: {str(e)}")


@app.get("/memories")
async def search_memories(
    query: str = Query(..., description="Search query"),
    user_id: Optional[str] = Query(default=None, description="User ID to search for"),
    limit: int = Query(default=10, description="Number of results to return")
):
    """
    Search memories using natural language query with timezone-aware filtering
    """
    try:
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required for memory search")
        
        # Get user's timezone
        user = db.get_user_by_id(user_id)
        user_timezone = user.get('timezone', 'UTC') if user else 'UTC'
        
        # Extract time entities from query
        query_intent = extract_query_intent(query)
        time_entities = query_intent.get('time_entities', [])
        
        # Get database memories with timezone-aware filtering first
        if time_entities:
            db_memories = db.get_memories_for_user_with_time_filter(user_id, time_entities, user_timezone, limit=50)
        else:
            db_memories = db.get_memories_for_user(user_id, limit=50)
        
        # Search using Mem0 with error handling, including time filtering
        try:
            mem0_results = memory_service.search_memories(
                query=query, 
                user_id=user_id, 
                limit=limit,
                time_entities=time_entities,
                user_timezone=user_timezone
            )
        except Exception as e:
            print(f"Mem0 search failed, falling back to database only: {e}")
            mem0_results = []
        
        # Apply relevance threshold filter to improve result quality
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
        
        # Enrich results with database information and enhanced formatting
        enriched_results = []
        for result in filtered_mem0_results:
            memory_id = result.get('id', result.get('memory_id'))
            
            # Find matching DB record
            db_match = None
            for db_mem in db_memories:
                if db_mem['mem0_memory_id'] == memory_id:
                    db_match = db_mem
                    break
            
            # Enhanced content formatting with context
            raw_content = result.get('memory', result.get('content', ''))
            metadata = result.get('metadata', {})
            
            # Format content with source and type information
            content_type = metadata.get('content_type', 'text')
            source = metadata.get('source', 'unknown')
            
            if content_type == 'image':
                formatted_content = f"📸 Image: {raw_content}"
            elif content_type == 'audio':
                formatted_content = f"🎤 Voice: {raw_content}"
            else:
                formatted_content = f"💬 Text: {raw_content}"
            
            # Add tags if available - handle both direct tags and insights.tags uniformly
            tags = []
            if 'insights' in metadata and 'tags' in metadata['insights']:
                tags = metadata['insights']['tags']
            elif 'tags' in metadata:
                tags = metadata['tags']
            
            enriched_result = {
                "memory_id": memory_id,
                "content": formatted_content,
                "raw_content": raw_content,
                "score": result.get('score', 0),
                "metadata": metadata,
                "database_info": {
                    **(db_match or {}),
                    "content_type": content_type,
                    "source": source,
                    "tags": tags,
                    "when_shared": db_match['created_at'] if db_match else None,
                    "interaction_date": db_match['interaction_date'] if db_match else None
                }
            }
            enriched_results.append(enriched_result)
        
        return {
            "query": query,
            "results": enriched_results,
            "total_found": len(enriched_results),
            "search_metadata": {
                "user_id": user_id,
                "user_timezone": user_timezone,
                "time_entities": time_entities,
                "limit": limit,
                "timestamp": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching memories: {str(e)}")


@app.get("/memories/list")
async def list_memories(
    user_id: Optional[str] = Query(default=None, description="User ID"),
    limit: int = Query(default=50, description="Number of memories to return"),
    time_filter: Optional[str] = Query(default=None, description="Time filter (e.g., 'today', 'yesterday', 'last week')")
):
    """
    List all memories for a user (from database) with optional timezone-aware filtering
    """
    try:
        if not user_id:
            # Return recent memories from all users
            recent_interactions = db.get_recent_interactions(limit=limit)
            memories = []
            
            for interaction in recent_interactions:
                user_memories = db.get_memories_for_user(interaction['user_id'], limit=5)
                memories.extend(user_memories)
        else:
            # Get user's timezone
            user = db.get_user_by_id(user_id)
            user_timezone = user.get('timezone', 'UTC') if user else 'UTC'
            
            if time_filter:
                # Extract time entities from the time filter
                query_intent = extract_query_intent(time_filter)
                time_entities = query_intent.get('time_entities', [])
                
                if time_entities:
                    memories = db.get_memories_for_user_with_time_filter(user_id, time_entities, user_timezone, limit)
                else:
                    memories = db.get_memories_for_user(user_id, limit)
            else:
                memories = db.get_memories_for_user(user_id, limit)
        
        # Sort by creation date
        memories.sort(key=lambda x: x['created_at'], reverse=True)
        
        return {
            "memories": memories[:limit],
            "total_count": len(memories),
            "user_id": user_id,
            "time_filter": time_filter,
            "user_timezone": user.get('timezone', 'UTC') if user_id and user else None,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing memories: {str(e)}")


@app.get("/interactions/recent")
async def get_recent_interactions(
    limit: int = Query(default=10, description="Number of recent interactions to return"),
    user_id: Optional[str] = Query(default=None, description="Filter by user ID")
):
    """
    Get recent user interactions
    """
    try:
        interactions = db.get_recent_interactions(user_id=user_id, limit=limit)
        
        return {
            "interactions": interactions,
            "total_count": len(interactions),
            "filters": {
                "user_id": user_id,
                "limit": limit
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recent interactions: {str(e)}")


@app.get("/analytics/summary")
async def get_analytics_summary():
    """
    Get analytics summary from database
    """
    try:
        summary = db.get_analytics_summary()
        
        # Add some computed metrics
        summary["metrics"] = {
            "avg_interactions_per_user": round(summary["total_interactions"] / max(summary["total_users"], 1), 2),
            "avg_memories_per_user": round(summary["total_memories"] / max(summary["total_users"], 1), 2),
            "memory_to_interaction_ratio": round(summary["total_memories"] / max(summary["total_interactions"], 1), 2)
        }
        
        summary["timestamp"] = datetime.now().isoformat()
        
        return summary
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting analytics: {str(e)}")



if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )