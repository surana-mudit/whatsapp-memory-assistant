"""
SQLAlchemy models for WhatsApp Memory Assistant
"""
from sqlalchemy import create_engine, Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
import uuid
from datetime import datetime

Base = declarative_base()


def generate_uuid():
    """Generate UUID as string"""
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = 'users'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    phone_number = Column(String, unique=True, nullable=False, index=True)
    whatsapp_id = Column(String, unique=True, nullable=False)
    timezone = Column(String, default='UTC')
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    interactions = relationship("Interaction", back_populates="user")
    memories = relationship("Memory", back_populates="user")
    
    def __repr__(self):
        return f"<User(phone_number='{self.phone_number}')>"


class Interaction(Base):
    __tablename__ = 'interactions'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey('users.id'), nullable=False)
    twilio_message_sid = Column(String, unique=True, nullable=False, index=True)
    message_type = Column(String, nullable=False)  # 'text', 'image', 'audio'
    content = Column(Text)
    media_url = Column(String)  # Original Twilio media URL
    media_file_path = Column(String)  # Local file path
    media_content_hash = Column(String, index=True)  # For deduplication
    transcript = Column(Text)  # For audio messages
    created_at = Column(DateTime, default=func.now(), index=True)
    
    # Relationships
    user = relationship("User", back_populates="interactions")
    memories = relationship("Memory", back_populates="interaction")
    
    def __repr__(self):
        return f"<Interaction(type='{self.message_type}', sid='{self.twilio_message_sid}')>"


class Memory(Base):
    __tablename__ = 'memories'
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey('users.id'), nullable=False)
    interaction_id = Column(String, ForeignKey('interactions.id'), nullable=False)
    mem0_memory_id = Column(String)  # Mem0's memory ID
    memory_content = Column(Text, nullable=False)
    tags = Column(Text)  # JSON array as text
    created_at = Column(DateTime, default=func.now(), index=True)
    
    # Relationships
    user = relationship("User", back_populates="memories")
    interaction = relationship("Interaction", back_populates="memories")
    
    def __repr__(self):
        return f"<Memory(content='{self.memory_content[:50]}...')>"