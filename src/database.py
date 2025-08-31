"""
Database operations using SQLAlchemy models and Alembic migrations
"""
from sqlalchemy import create_engine, desc, func
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Generator
import json
from datetime import datetime, timedelta
import pytz

from .models import Base, User, Interaction, Memory


class Database:
    def __init__(self, db_url: str = "sqlite:///database.db"):
        # Simple SQLite configuration
        if "sqlite" in db_url:
            self.engine = create_engine(
                db_url,
                echo=False,
                connect_args={"check_same_thread": False}
            )
        else:
            self.engine = create_engine(db_url, echo=False)
        
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables if they don't exist (for development)
        # In production, use alembic migrations
        Base.metadata.create_all(bind=self.engine)
    
    def _get_timezone_aware_date_range(self, time_entity: Dict, user_timezone: str) -> tuple:
        """Convert time entity to UTC date range for database queries"""
        user_tz = pytz.timezone(user_timezone)
        now = datetime.now(user_tz)
        
        if time_entity['type'] == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
        elif time_entity['type'] == 'yesterday':
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = end_date - timedelta(days=1)
        elif time_entity['type'] == 'this_week':
            days_since_monday = now.weekday()
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            end_date = start_date + timedelta(days=7)
        elif time_entity['type'] == 'last_week':
            days_since_monday = now.weekday()
            this_week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            start_date = this_week_start - timedelta(days=7)
            end_date = this_week_start
        elif time_entity['type'] == 'this_month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = start_date + timedelta(days=32)
            end_date = next_month.replace(day=1)
        elif time_entity['type'] == 'last_month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date
            start_date = (start_date - timedelta(days=1)).replace(day=1)
        elif time_entity['type'] == 'days_ago':
            days = int(time_entity['value'])
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_date = end_date - timedelta(days=days)
        elif time_entity['type'] == 'hours_ago':
            hours = int(time_entity['value'])
            end_date = now
            start_date = end_date - timedelta(hours=hours)
        elif time_entity['type'] == 'last_hours':
            hours = int(time_entity['value'])
            end_date = now
            start_date = end_date - timedelta(hours=hours)
        elif time_entity['type'] == 'weeks_ago':
            weeks = int(time_entity['value'])
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_date = end_date - timedelta(weeks=weeks)
        elif time_entity['type'] == 'months_ago':
            months = int(time_entity['value'])
            end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_date = end_date - timedelta(days=30 * months)  # Approximate
        else:
            return None, None
        
        # Convert to UTC for database storage
        start_date_utc = start_date.astimezone(pytz.UTC).replace(tzinfo=None)
        end_date_utc = end_date.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return start_date_utc, end_date_utc
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Context manager for database sessions"""
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
        """Create or get existing user"""
        with self.get_session() as session:
            # Check if user exists
            existing_user = session.query(User).filter_by(phone_number=phone_number).first()
            if existing_user:
                return existing_user.id
            
            # Create new user
            user = User(
                phone_number=phone_number,
                whatsapp_id=whatsapp_id,
                timezone=timezone
            )
            session.add(user)
            session.flush()  # Get the ID
            return user.id
    
    def get_user_by_phone(self, phone_number: str) -> Optional[Dict]:
        """Get user by phone number"""
        with self.get_session() as session:
            user = session.query(User).filter_by(phone_number=phone_number).first()
            if user:
                return {
                    'id': user.id,
                    'phone_number': user.phone_number,
                    'whatsapp_id': user.whatsapp_id,
                    'timezone': user.timezone,
                    'created_at': user.created_at.isoformat(),
                    'updated_at': user.updated_at.isoformat()
                }
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by user ID"""
        with self.get_session() as session:
            user = session.get(User, user_id)
            if user:
                return {
                    'id': user.id,
                    'phone_number': user.phone_number,
                    'whatsapp_id': user.whatsapp_id,
                    'timezone': user.timezone,
                    'created_at': user.created_at.isoformat(),
                    'updated_at': user.updated_at.isoformat()
                }
            return None
    
    def create_interaction(self, user_id: str, twilio_message_sid: str, message_type: str, 
                          content: str = None, media_url: str = None, 
                          media_file_path: str = None, media_content_hash: str = None,
                          transcript: str = None) -> str:
        """Create new interaction with idempotency check"""
        with self.get_session() as session:
            # Check for existing interaction (idempotency)
            existing = session.query(Interaction).filter_by(
                twilio_message_sid=twilio_message_sid
            ).first()
            if existing:
                return existing.id
            
            # Create new interaction
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
    
    def get_interaction_by_sid(self, twilio_message_sid: str) -> Optional[Dict]:
        """Get interaction by Twilio message SID"""
        with self.get_session() as session:
            interaction = session.query(Interaction).filter_by(
                twilio_message_sid=twilio_message_sid
            ).first()
            
            if interaction:
                return {
                    'id': interaction.id,
                    'user_id': interaction.user_id,
                    'twilio_message_sid': interaction.twilio_message_sid,
                    'message_type': interaction.message_type,
                    'content': interaction.content,
                    'media_url': interaction.media_url,
                    'media_file_path': interaction.media_file_path,
                    'media_content_hash': interaction.media_content_hash,
                    'transcript': interaction.transcript,
                    'created_at': interaction.created_at.isoformat()
                }
            return None
    
    def check_media_exists(self, content_hash: str) -> Optional[str]:
        """Check if media with this hash already exists"""
        with self.get_session() as session:
            interaction = session.query(Interaction).filter_by(
                media_content_hash=content_hash
            ).first()
            return interaction.media_file_path if interaction else None
    
    def update_interaction(self, interaction_id: str, media_file_path: str = None, 
                          media_content_hash: str = None, transcript: str = None) -> None:
        """Update interaction with processed media information"""
        with self.get_session() as session:
            interaction = session.get(Interaction, interaction_id)
            if interaction:
                if media_file_path:
                    interaction.media_file_path = media_file_path
                if media_content_hash:
                    interaction.media_content_hash = media_content_hash
                if transcript:
                    interaction.transcript = transcript
    
    def create_memory(self, user_id: str, interaction_id: str, mem0_memory_id: str, 
                     memory_content: str, tags: List[str] = None) -> str:
        """Create memory record"""
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
    
    def get_memories_for_user(self, user_id: str, limit: int = 50, user_timezone: str = 'UTC', 
                              start_date: datetime = None, end_date: datetime = None) -> List[Dict]:
        """Get all memories for a user, newest first with optional timezone-aware date filtering"""
        with self.get_session() as session:
            query = session.query(Memory, Interaction).join(
                Interaction, Memory.interaction_id == Interaction.id
            ).filter(Memory.user_id == user_id)
            
            # Add date range filtering if provided
            if start_date:
                query = query.filter(Memory.created_at >= start_date)
            if end_date:
                query = query.filter(Memory.created_at < end_date)
                
            query = query.order_by(desc(Memory.created_at)).limit(limit)
            
            results = []
            for memory, interaction in query.all():
                results.append({
                    'id': memory.id,
                    'user_id': memory.user_id,
                    'interaction_id': memory.interaction_id,
                    'mem0_memory_id': memory.mem0_memory_id,
                    'memory_content': memory.memory_content,
                    'tags': memory.tags,
                    'created_at': memory.created_at.isoformat(),
                    'message_type': interaction.message_type,
                    'interaction_date': interaction.created_at.isoformat()
                })
            return results
    
    def get_memories_for_user_with_time_filter(self, user_id: str, time_entities: List[Dict], 
                                             user_timezone: str = 'UTC', limit: int = 50) -> List[Dict]:
        """Get memories for a user with timezone-aware time filtering using time entities"""
        if not time_entities:
            return self.get_memories_for_user(user_id, limit=limit, user_timezone=user_timezone)
        
        # Apply the first time entity for filtering (multiple entities could be combined in the future)
        time_entity = time_entities[0]
        start_date, end_date = self._get_timezone_aware_date_range(time_entity, user_timezone)
        
        if start_date is None or end_date is None:
            return self.get_memories_for_user(user_id, limit=limit, user_timezone=user_timezone)
        
        return self.get_memories_for_user(
            user_id=user_id, 
            limit=limit, 
            user_timezone=user_timezone,
            start_date=start_date,
            end_date=end_date
        )
    
    def get_recent_interactions(self, user_id: str = None, limit: int = 10) -> List[Dict]:
        """Get recent interactions, optionally filtered by user"""
        with self.get_session() as session:
            query = session.query(Interaction, User).join(
                User, Interaction.user_id == User.id
            ).order_by(desc(Interaction.created_at)).limit(limit)
            
            if user_id:
                query = query.filter(Interaction.user_id == user_id)
            
            results = []
            for interaction, user in query.all():
                results.append({
                    'id': interaction.id,
                    'user_id': interaction.user_id,
                    'twilio_message_sid': interaction.twilio_message_sid,
                    'message_type': interaction.message_type,
                    'content': interaction.content,
                    'media_url': interaction.media_url,
                    'media_file_path': interaction.media_file_path,
                    'media_content_hash': interaction.media_content_hash,
                    'transcript': interaction.transcript,
                    'created_at': interaction.created_at.isoformat(),
                    'phone_number': user.phone_number
                })
            return results
    
    def get_analytics_summary(self) -> Dict[str, Any]:
        """Get analytics summary from database"""
        with self.get_session() as session:
            # Total counts
            total_users = session.query(User).count()
            total_interactions = session.query(Interaction).count()
            total_memories = session.query(Memory).count()
            
            # Interactions by type
            interactions_by_type = {}
            type_counts = session.query(
                Interaction.message_type, 
                func.count(Interaction.id).label('count')
            ).group_by(Interaction.message_type).all()
            
            for message_type, count in type_counts:
                interactions_by_type[message_type] = count
            
            # Last ingest time
            last_interaction = session.query(Interaction).order_by(
                desc(Interaction.created_at)
            ).first()
            last_ingest = last_interaction.created_at.isoformat() if last_interaction else None
            
            # Most active users
            top_users_query = session.query(
                User.phone_number,
                func.count(Interaction.id).label('interaction_count')
            ).join(Interaction).group_by(User.id, User.phone_number).order_by(
                desc('interaction_count')
            ).limit(5)
            
            top_users = [
                {'phone_number': phone, 'interaction_count': count}
                for phone, count in top_users_query.all()
            ]
            
            return {
                "total_users": total_users,
                "total_interactions": total_interactions,
                "total_memories": total_memories,
                "interactions_by_type": interactions_by_type,
                "last_ingest_time": last_ingest,
                "top_users": top_users
            }


# Global database instance
db = Database()