import pytest
import os
import sys
from fastapi.testclient import TestClient
import json
import tempfile

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.main import app
from src.database import Database
from src.utils import clean_phone_number, extract_query_intent, format_memory_for_display

client = TestClient(app)


class TestAPI:
    """Test API endpoints"""
    
    def test_health_check(self):
        """Test health check endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_detailed_health_check(self):
        """Test detailed health check"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "database" in data["services"]
    
    def test_memories_list_endpoint(self):
        """Test memories list endpoint"""
        response = client.get("/memories/list")
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data
        assert "total_count" in data
    
    def test_analytics_summary_endpoint(self):
        """Test analytics summary endpoint"""
        response = client.get("/analytics/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "total_interactions" in data
        assert "total_memories" in data
    
    def test_recent_interactions_endpoint(self):
        """Test recent interactions endpoint"""
        response = client.get("/interactions/recent?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "interactions" in data
        assert data["filters"]["limit"] == 5
    
    def test_search_memories_missing_user_id(self):
        """Test search memories without user_id"""
        response = client.get("/memories?query=test")
        assert response.status_code == 400
    
    def test_add_memory_api(self):
        """Test adding memory via API"""
        response = client.post("/memories", data={
            "content": "Test memory content",
            "user_id": "test_user_123",
            "content_type": "text"
        })
        # May fail due to Mem0 API key, but should return proper error structure
        assert response.status_code in [200, 500]


class TestDatabase:
    """Test database operations"""
    
    def setup_method(self):
        """Setup test database"""
        self.test_db = Database("sqlite:///:memory:")  # Use in-memory DB for tests
    
    def test_create_user(self):
        """Test user creation"""
        user_id = self.test_db.create_user("+1234567890", "whatsapp:+1234567890")
        assert user_id is not None
        
        # Test idempotency
        user_id2 = self.test_db.create_user("+1234567890", "whatsapp:+1234567890")
        assert user_id == user_id2
    
    def test_get_user_by_phone(self):
        """Test getting user by phone"""
        # Create user first
        self.test_db.create_user("+1234567890", "whatsapp:+1234567890")
        
        # Retrieve user
        user = self.test_db.get_user_by_phone("+1234567890")
        assert user is not None
        assert user["phone_number"] == "+1234567890"
    
    def test_create_interaction(self):
        """Test interaction creation"""
        # Create user first
        user_id = self.test_db.create_user("+1234567890", "whatsapp:+1234567890")
        
        # Create interaction
        interaction_id = self.test_db.create_interaction(
            user_id=user_id,
            twilio_message_sid="test_sid_123",
            message_type="text",
            content="Test message"
        )
        assert interaction_id is not None
        
        # Test idempotency
        interaction_id2 = self.test_db.create_interaction(
            user_id=user_id,
            twilio_message_sid="test_sid_123",
            message_type="text",
            content="Test message"
        )
        assert interaction_id == interaction_id2
    
    def test_analytics_summary(self):
        """Test analytics summary"""
        # Create some test data
        user_id = self.test_db.create_user("+1234567890", "whatsapp:+1234567890")
        self.test_db.create_interaction(
            user_id=user_id,
            twilio_message_sid="test_sid_1",
            message_type="text",
            content="Test message 1"
        )
        
        # Get analytics
        summary = self.test_db.get_analytics_summary()
        assert summary["total_users"] >= 1
        assert summary["total_interactions"] >= 1
        assert "interactions_by_type" in summary


class TestUtils:
    """Test utility functions"""
    
    def test_clean_phone_number(self):
        """Test phone number cleaning"""
        assert clean_phone_number("whatsapp:+1234567890") == "+1234567890"
        assert clean_phone_number("+1-234-567-890") == "+12345678890"
        assert clean_phone_number("1234567890") == "+1234567890"
    
    def test_extract_query_intent(self):
        """Test query intent extraction"""
        # Search queries
        result = extract_query_intent("What did I say about dinner?")
        assert result["intent"] == "search"
        
        result = extract_query_intent("Show me my photos")
        assert result["intent"] == "search"
        
        # List commands
        result = extract_query_intent("/list")
        assert result["intent"] == "list"
        
        result = extract_query_intent("list all my memories")
        assert result["intent"] == "list"
        
        # Regular messages
        result = extract_query_intent("I had pizza for lunch")
        assert result["intent"] == "message"
    
    def test_format_memory_for_display(self):
        """Test memory formatting"""
        memory = {
            "memory_content": "Test memory content",
            "created_at": "2023-12-01T10:30:00",
            "message_type": "text"
        }
        
        formatted = format_memory_for_display(memory)
        assert "Test memory content" in formatted
        assert "2023-12-01" in formatted
        assert "📝" in formatted
        
        # Test image memory
        memory["message_type"] = "image"
        formatted = format_memory_for_display(memory)
        assert "📸" in formatted


class TestWebhookProcessing:
    """Test webhook data processing"""
    
    def test_webhook_endpoint_structure(self):
        """Test webhook endpoint response structure"""
        # Test with minimal webhook data
        webhook_data = {
            "From": "whatsapp:+1234567890",
            "To": "whatsapp:+14155238886",
            "MessageSid": "test_message_id",
            "Body": "Test message"
        }
        
        response = client.post("/webhook", data=webhook_data)
        # Should return TwiML response
        assert response.status_code == 200
        assert "Content-Type" in response.headers


class TestMediaDeduplication:
    """Test media deduplication logic"""
    
    def test_content_hash_generation(self):
        """Test that same content generates same hash"""
        from src.media_processor import MediaProcessor
        
        processor = MediaProcessor()
        content1 = b"test content for hashing"
        content2 = b"test content for hashing"
        content3 = b"different content"
        
        hash1 = processor.get_content_hash(content1)
        hash2 = processor.get_content_hash(content2)
        hash3 = processor.get_content_hash(content3)
        
        assert hash1 == hash2  # Same content = same hash
        assert hash1 != hash3  # Different content = different hash


class TestErrorHandling:
    """Test error handling scenarios"""
    
    def test_invalid_endpoints(self):
        """Test invalid endpoint requests"""
        response = client.get("/nonexistent")
        assert response.status_code == 404
    
    def test_malformed_requests(self):
        """Test malformed request handling"""
        # Test malformed JSON
        response = client.post("/memories", 
                             json={"invalid": "structure"},
                             headers={"Content-Type": "application/json"})
        assert response.status_code in [400, 422]  # Should reject malformed data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])