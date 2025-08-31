#!/usr/bin/env python3
"""
Seed script to populate the database with sample data for testing and evaluation
"""
import sys
import os
import json
from datetime import datetime, timedelta

# Add src directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import models directly
from models import Base, User, Interaction, Memory

# Create a custom database instance that doesn't use relative imports
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Generator
import json
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_url: str = "sqlite:///database.db"):
        if "sqlite" in db_url:
            self.engine = create_engine(
                db_url,
                echo=False,
                connect_args={"check_same_thread": False}
            )
        else:
            self.engine = create_engine(db_url, echo=False)
        
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
    
    @contextmanager
    def get_session(self) -> Generator:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def create_user(self, phone_number: str, whatsapp_id: str, timezone: str = "UTC") -> str:
        with self.get_session() as session:
            existing_user = session.query(User).filter_by(phone_number=phone_number).first()
            if existing_user:
                return existing_user.id
            
            user = User(
                phone_number=phone_number,
                whatsapp_id=whatsapp_id,
                timezone=timezone
            )
            session.add(user)
            session.flush()
            return user.id
    
    def create_interaction(self, user_id: str, twilio_message_sid: str, message_type: str, 
                          content: str = None, media_url: str = None, 
                          media_file_path: str = None, media_content_hash: str = None,
                          transcript: str = None) -> str:
        with self.get_session() as session:
            existing = session.query(Interaction).filter_by(
                twilio_message_sid=twilio_message_sid
            ).first()
            if existing:
                return existing.id
            
            interaction = Interaction(
                user_id=user_id,
                twilio_message_sid=twilio_message_sid,
                message_type=message_type,
                content=content,
                media_url=media_url,
                media_file_path=media_file_path,
                media_content_hash=media_content_hash,
                transcript=transcript
            )
            session.add(interaction)
            session.flush()
            return interaction.id
    
    def create_memory(self, user_id: str, interaction_id: str, mem0_memory_id: str, 
                     memory_content: str, tags: List[str] = None) -> str:
        with self.get_session() as session:
            tags_json = json.dumps(tags) if tags else None
            
            memory = Memory(
                user_id=user_id,
                interaction_id=interaction_id,
                mem0_memory_id=mem0_memory_id,
                memory_content=memory_content,
                tags=tags_json
            )
            session.add(memory)
            session.flush()
            return memory.id

# Create database instance
db = Database()
import uuid

def generate_sample_users():
    """Create sample users with different timezones"""
    users_data = [
        {
            "phone_number": "+1234567890",
            "whatsapp_id": "whatsapp:+1234567890",
            "timezone": "America/New_York"
        },
        {
            "phone_number": "+1987654321", 
            "whatsapp_id": "whatsapp:+1987654321",
            "timezone": "America/Los_Angeles"
        },
        {
            "phone_number": "+441234567890",
            "whatsapp_id": "whatsapp:+441234567890", 
            "timezone": "Europe/London"
        }
    ]
    
    user_ids = []
    for user_data in users_data:
        user_id = db.create_user(**user_data)
        user_ids.append(user_id)
        print(f"Created user: {user_data['phone_number']} (ID: {user_id})")
    
    return user_ids

def generate_sample_interactions(user_ids):
    """Create sample interactions of different types with realistic timestamps"""
    interactions_data = [
        # Text interactions
        {
            "user_id": user_ids[0],
            "message_type": "text",
            "content": "I'm planning to cook pasta tonight with mushrooms and cheese",
            "days_ago": 1
        },
        {
            "user_id": user_ids[0], 
            "message_type": "text",
            "content": "Grocery list: tomatoes, bread, milk, pasta, mushrooms, parmesan cheese",
            "days_ago": 2
        },
        {
            "user_id": user_ids[1],
            "message_type": "text", 
            "content": "Meeting with the team tomorrow at 3 PM. Need to prepare presentation slides.",
            "days_ago": 3
        },
        
        # Image interactions
        {
            "user_id": user_ids[0],
            "message_type": "image",
            "content": "New haircut photo - looks great!",
            "media_file_path": "./media/images/sample_haircut.jpg",
            "media_content_hash": "abc123_haircut_hash",
            "days_ago": 5
        },
        {
            "user_id": user_ids[2],
            "message_type": "image",
            "content": "Beautiful sunset from the beach vacation",
            "media_file_path": "./media/images/sample_sunset.jpg", 
            "media_content_hash": "def456_sunset_hash",
            "days_ago": 7
        },
        
        # Audio interactions with transcripts
        {
            "user_id": user_ids[1],
            "message_type": "audio",
            "content": "Voice note about daily tasks",
            "media_file_path": "./media/audio/sample_todos.ogg",
            "media_content_hash": "ghi789_audio_hash",
            "transcript": "Today's todos: grocery shopping, call mom, finish quarterly report, book dentist appointment",
            "days_ago": 4
        },
        {
            "user_id": user_ids[2],
            "message_type": "audio",
            "content": "Recording about weekend plans",
            "media_file_path": "./media/audio/sample_weekend.ogg",
            "media_content_hash": "jkl012_weekend_hash", 
            "transcript": "This weekend I want to visit the new art gallery downtown and try that Italian restaurant everyone's been talking about",
            "days_ago": 6
        }
    ]
    
    interaction_ids = []
    base_time = datetime.now()
    
    for i, interaction_data in enumerate(interactions_data):
        # Create realistic timestamps
        created_time = base_time - timedelta(days=interaction_data.pop("days_ago"))
        
        # Generate unique Twilio message SID
        interaction_data["twilio_message_sid"] = f"SM{str(uuid.uuid4()).replace('-', '')[:32]}"
        
        interaction_id = db.create_interaction(**interaction_data)
        interaction_ids.append(interaction_id)
        
        # Update the created_at timestamp to simulate realistic timing
        with db.get_session() as session:
            interaction = session.get(Interaction, interaction_id)
            if interaction:
                interaction.created_at = created_time
        
        print(f"Created {interaction_data['message_type']} interaction: {interaction_id}")
    
    return interaction_ids

def generate_sample_memories(user_ids, interaction_ids):
    """Create sample memories linked to interactions"""
    memories_data = [
        {
            "user_id": user_ids[0],
            "interaction_id": interaction_ids[0], 
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User plans to cook pasta with mushrooms and cheese for dinner",
            "tags": ["cooking", "dinner", "pasta", "recipe"]
        },
        {
            "user_id": user_ids[0],
            "interaction_id": interaction_ids[1],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User's grocery shopping list includes tomatoes, bread, milk, pasta, mushrooms, and parmesan cheese",
            "tags": ["grocery", "shopping", "food", "ingredients"]
        },
        {
            "user_id": user_ids[1],
            "interaction_id": interaction_ids[2],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User has a team meeting scheduled for tomorrow at 3 PM and needs to prepare presentation slides",
            "tags": ["work", "meeting", "presentation", "schedule"]
        },
        {
            "user_id": user_ids[0],
            "interaction_id": interaction_ids[3],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User got a new haircut and shared a photo showing the new look",
            "tags": ["personal", "appearance", "haircut", "photo"]
        },
        {
            "user_id": user_ids[2],
            "interaction_id": interaction_ids[4],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User shared a beautiful sunset photo from their beach vacation",
            "tags": ["vacation", "beach", "sunset", "photo", "travel"]
        },
        {
            "user_id": user_ids[1],
            "interaction_id": interaction_ids[5],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User's daily todos include grocery shopping, calling mom, finishing quarterly report, and booking dentist appointment",
            "tags": ["todos", "tasks", "personal", "work", "family"]
        },
        {
            "user_id": user_ids[2],
            "interaction_id": interaction_ids[6],
            "mem0_memory_id": f"mem0_{str(uuid.uuid4())}",
            "memory_content": "User plans to visit new art gallery and try Italian restaurant this weekend",
            "tags": ["weekend", "plans", "art", "restaurant", "social"]
        }
    ]
    
    memory_ids = []
    for memory_data in memories_data:
        memory_id = db.create_memory(**memory_data)
        memory_ids.append(memory_id)
        print(f"Created memory: {memory_id}")
    
    return memory_ids

def create_sample_media_directories():
    """Create media directories and placeholder files for demonstration"""
    media_dirs = [
        "./media/images",
        "./media/audio", 
        "./media/transcripts"
    ]
    
    for directory in media_dirs:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")
    
    # Create placeholder files
    placeholder_files = [
        "./media/images/sample_haircut.jpg",
        "./media/images/sample_sunset.jpg",
        "./media/audio/sample_todos.ogg",
        "./media/audio/sample_weekend.ogg"
    ]
    
    for file_path in placeholder_files:
        if not os.path.exists(file_path):
            with open(file_path, 'w') as f:
                f.write(f"# Placeholder file for {os.path.basename(file_path)}\n")
            print(f"Created placeholder: {file_path}")

def main():
    """Main seeding function"""
    print("🌱 Starting database seeding...")
    print("=" * 50)
    
    # Create media directories
    print("\n📁 Creating media directories...")
    create_sample_media_directories()
    
    # Generate sample data
    print("\n👥 Creating sample users...")
    user_ids = generate_sample_users()
    
    print(f"\n💬 Creating sample interactions...")
    interaction_ids = generate_sample_interactions(user_ids)
    
    print(f"\n🧠 Creating sample memories...")
    memory_ids = generate_sample_memories(user_ids, interaction_ids)
    
    print("\n" + "=" * 50)
    print("✅ Database seeding completed successfully!")
    print(f"📊 Summary:")
    print(f"   - Users created: {len(user_ids)}")
    print(f"   - Interactions created: {len(interaction_ids)}")
    print(f"   - Memories created: {len(memory_ids)}")
    print("\n🚀 Your WhatsApp Memory Assistant is ready for testing!")

if __name__ == "__main__":
    main()