import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz


def clean_phone_number(phone_number: str) -> str:
    """Clean and normalize phone number"""
    # Remove whatsapp: prefix and any spaces/dashes
    cleaned = phone_number.replace('whatsapp:', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    # Ensure it starts with +
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    
    return cleaned


def extract_query_intent(text: str) -> Dict[str, any]:
    """Extract intent and entities from user query"""
    text_lower = text.lower().strip()
    
    intent_patterns = {
        'search': [
            r'what.*did.*i.*', r'show.*me.*', r'find.*', r'where.*', r'when.*',
            r'remind.*me.*about.*', r'do.*you.*remember.*', r'.*\?'
        ],
        'list': [r'/list', r'list.*all', r'show.*all.*memories', r'my.*memories'],
        'delete': [r'delete.*', r'remove.*', r'forget.*'],
        'help': [r'help', r'how.*', r'what.*can.*you.*do']
    }
    
    # Detect intent
    intent = 'message'  # default
    for intent_name, patterns in intent_patterns.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                intent = intent_name
                break
        if intent != 'message':
            break
    
    # Extract time references
    time_entities = extract_time_entities(text)
    
    # Extract keywords
    keywords = extract_keywords(text)
    
    return {
        'intent': intent,
        'time_entities': time_entities,
        'keywords': keywords,
        'original_text': text
    }


def extract_time_entities(text: str) -> List[Dict[str, str]]:
    """Extract time-related entities from text"""
    text_lower = text.lower()
    time_entities = []
    
    time_patterns = {
        'today': r'\btoday\b',
        'yesterday': r'\byesterday\b',
        'this_week': r'\bthis week\b',
        'last_week': r'\blast week\b',
        'this_month': r'\bthis month\b',
        'last_month': r'\blast month\b',
        'hours_ago': r'(\d+)\s+hours?\s+ago',
        'days_ago': r'(\d+)\s+days?\s+ago',
        'weeks_ago': r'(\d+)\s+weeks?\s+ago',
        'months_ago': r'(\d+)\s+months?\s+ago',
        'last_hours': r'\blast\s+(\d+)\s+hours?\b'
    }
    
    for entity_type, pattern in time_patterns.items():
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            time_entities.append({
                'type': entity_type,
                'text': match.group(0),
                'value': match.group(1) if match.groups() else None
            })
    
    return time_entities


def extract_keywords(text: str) -> List[str]:
    """Extract relevant keywords from text"""
    # Remove common words and extract meaningful terms
    stop_words = {
        'i', 'me', 'my', 'you', 'your', 'the', 'a', 'an', 'and', 'or', 'but',
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was',
        'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'can', 'may', 'might', 'what', 'when',
        'where', 'who', 'how', 'why', 'this', 'that', 'these', 'those'
    }
    
    # Clean and split text
    cleaned = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [word.strip() for word in cleaned.split() if len(word) > 2]
    
    # Filter out stop words
    keywords = [word for word in words if word not in stop_words]
    
    return keywords[:10]  # Limit to top 10 keywords


def get_timezone_aware_date(date_string: str, user_timezone: str = 'UTC') -> datetime:
    """Convert date string to timezone-aware datetime"""
    try:
        # Parse the date string (assuming ISO format)
        dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        
        # Convert to user timezone
        user_tz = pytz.timezone(user_timezone)
        return dt.astimezone(user_tz)
    except:
        return datetime.now(pytz.timezone(user_timezone))


def filter_by_time_range(items: List[Dict], time_entity: Dict, timezone: str = 'UTC') -> List[Dict]:
    """Filter items by time range based on extracted time entity"""
    now = datetime.now(pytz.timezone(timezone))
    
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
    else:
        return items  # No filtering
    
    filtered_items = []
    for item in items:
        item_date = get_timezone_aware_date(item['created_at'], timezone)
        if start_date <= item_date < end_date:
            filtered_items.append(item)
    
    return filtered_items


def format_memory_for_display(memory: Dict, include_metadata: bool = True) -> str:
    """Format memory for user-friendly display"""
    content = memory.get('memory_content', memory.get('content', ''))
    
    # Truncate long content
    if len(content) > 100:
        content = content[:97] + '...'
    
    # Format date
    created_at = memory.get('created_at', '')
    if created_at:
        try:
            date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            date_str = date_obj.strftime('%Y-%m-%d %H:%M')
        except:
            date_str = created_at[:16]  # Fallback
    else:
        date_str = 'Unknown date'
    
    formatted = f"📝 {content} ({date_str})"
    
    if include_metadata:
        # Add tags if available
        tags = memory.get('tags', [])
        if isinstance(tags, str):
            try:
                import json
                tags = json.loads(tags)
            except:
                tags = []
        
        if tags:
            tag_str = ', '.join(tags[:3])  # Show max 3 tags
            formatted += f" 🏷️ {tag_str}"
        
        # Add message type indicator
        message_type = memory.get('message_type', '')
        if message_type == 'image':
            formatted = formatted.replace('📝', '📸')
        elif message_type == 'audio':
            formatted = formatted.replace('📝', '🎤')
    
    return formatted


def validate_webhook_data(data: Dict) -> bool:
    """Validate Twilio webhook data"""
    required_fields = ['From', 'To', 'MessageSid']
    return all(field in data for field in required_fields)


def sanitize_content(content: str, max_length: int = 10000) -> str:
    """Sanitize user content"""
    if not content:
        return ""
    
    # Remove potentially harmful content
    content = content.strip()
    
    # Limit length
    if len(content) > max_length:
        content = content[:max_length] + "... [truncated]"
    
    return content


def generate_response_greeting(user_name: str = None) -> str:
    """Generate friendly greeting for new users"""
    greetings = [
        "👋 Hi there! I'm your WhatsApp Memory Assistant. I can help you remember things by storing your messages, photos, and voice notes!",
        "🌟 Welcome! I'm here to be your digital memory. Send me anything you want to remember - text, images, or voice messages!",
        "💡 Hello! I'm your personal memory keeper. I'll store and help you recall your messages, photos, and voice notes. Try asking me to 'list' your memories!"
    ]
    
    import random
    greeting = random.choice(greetings)
    
    if user_name:
        greeting = greeting.replace("Hi there!", f"Hi {user_name}!")
        greeting = greeting.replace("Welcome!", f"Welcome {user_name}!")
        greeting = greeting.replace("Hello!", f"Hello {user_name}!")
    
    return greeting


def create_help_message() -> str:
    """Create help message for users"""
    return """🤖 WhatsApp Memory Assistant Help

What I can do:
📝 Remember your text messages
📸 Store and analyze your photos  
🎤 Transcribe and save voice messages
🔍 Search your memories with natural language
📋 List all your saved memories

Commands:
• Send any message - I'll save it as a memory
• Send photos/voice notes - I'll process and remember them
• Ask questions like "What did I say about dinner?"
• Type "/list" to see all your memories
• Ask "show me memories from last week"

I understand time references like:
- today, yesterday, last week, this month
- "3 days ago", "2 weeks ago"

Try me out! Send a message, photo, or voice note and I'll remember it for you! 🚀"""


def estimate_processing_time(message_type: str, file_size: int = 0) -> int:
    """Estimate processing time in seconds"""
    if message_type == 'text':
        return 1
    elif message_type == 'image':
        return 3 + (file_size // 1000000)  # Base 3s + 1s per MB
    elif message_type == 'audio':
        return 5 + (file_size // 500000)   # Base 5s + 1s per 500KB (transcription)
    else:
        return 2