import os
import base64
import json
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class LLMService:
    """
    LLM service using Portkey as gateway with virtual key authentication.
    
    Environment variables required:
    - PORTKEY_API_KEY: Your Portkey API key
    - PORTKEY_VIRTUAL_KEY: Virtual key for your OpenRouter/LLM provider
    - LLM_MODEL: Model to use (default: gpt-4o-mini)
    """
    def __init__(self):
        self.portkey_api_key = os.getenv("PORTKEY_API_KEY")
        self.portkey_virtual_key = os.getenv("PORTKEY_VIRTUAL_KEY")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")  # Default to gpt-4o-mini
        
        # Initialize Portkey client
        try:
            from portkey_ai import Portkey
            if self.portkey_api_key and self.portkey_virtual_key:
                self.client = Portkey(
                    api_key=self.portkey_api_key,
                    virtual_key=self.portkey_virtual_key
                )
            else:
                print("Warning: Portkey credentials not found, LLM features disabled")
                self.client = None
        except Exception as e:
            print(f"Warning: Could not initialize Portkey client: {e}")
            self.client = None
    
    def encode_image_to_base64(self, image_path: str) -> Optional[str]:
        """Convert local image file to base64 string"""
        try:
            with open(image_path, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode('utf-8')
            return encoded
        except Exception as e:
            print(f"Error encoding image to base64: {e}")
            return None
    
    def analyze_image(self, image_path: str) -> Optional[str]:
        """Analyze image and return descriptive text using LLM"""
        if not self.client:
            return f"Image file: {Path(image_path).name}"
        
        try:
            # Encode image to base64
            base64_image = self.encode_image_to_base64(image_path)
            if not base64_image:
                return f"Image file: {Path(image_path).name}"
            
            # Determine image format
            image_format = Path(image_path).suffix.lower().replace('.', '')
            if image_format == 'jpg':
                image_format = 'jpeg'
            
            # Create LLM request for image analysis
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Provide a concise, descriptive summary of this image in 1-2 sentences. Focus on the main subjects, setting, and key details that would help someone understand what they're looking at."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}"
                            }
                        }
                    ]
                }],
                max_tokens=150  # Keep response concise
            )
            
            description = response.choices[0].message.content
            return description.strip() if description else f"Image file: {Path(image_path).name}"
            
        except Exception as e:
            print(f"Error analyzing image with LLM: {e}")
            return f"Image file: {Path(image_path).name}"
    
    def extract_content_insights(self, content: str, content_type: str = "text", 
                               image_description: str = None) -> Dict[str, Any]:
        """Extract insights, tags, categories, and sentiment from content using LLM"""
        if not self.client:
            # Fallback to basic structure
            return {
                "tags": [],
                "category": "general",
                "sentiment": "neutral"
            }
        
        try:
            # Prepare content for analysis
            analysis_content = content
            if image_description and content_type == "image":
                analysis_content = f"Image description: {image_description}"
            elif image_description and content:
                analysis_content = f"Text: {content}\nImage description: {image_description}"
            
            # Create LLM request for content insights
            prompt = f"""Analyze the following content and extract insights in JSON format:

Content: {analysis_content}
Content Type: {content_type}

Please provide a JSON response with:
1. "tags": Array of 2-4 relevant tags (e.g., ["food", "social", "planning"])
2. "category": Main category (e.g., "food", "productivity", "personal", "shopping", "entertainment", "travel", "health", "work", "social", "general")
3. "sentiment": Emotional tone ("positive", "negative", "neutral")

Respond ONLY with valid JSON, no additional text."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                max_tokens=100,
                temperature=0.3  # Lower temperature for more consistent responses
            )
            
            # Parse JSON response
            response_text = response.choices[0].message.content
            if not response_text:
                raise ValueError("Empty response from LLM")
            
            response_text = response_text.strip()
            # Remove any markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            insights = json.loads(response_text)
            
            # Validate and clean response
            if not isinstance(insights.get("tags"), list):
                insights["tags"] = []
            if not isinstance(insights.get("category"), str):
                insights["category"] = "general"
            if insights.get("sentiment") not in ["positive", "negative", "neutral"]:
                insights["sentiment"] = "neutral"
            
            return insights
            
        except Exception as e:
            print(f"Error extracting content insights with LLM: {e}")
            # Fallback response
            return {
                "tags": [],
                "category": "general", 
                "sentiment": "neutral"
            }
    
    def analyze_image_with_content_insights(self, image_path: str, 
                                          additional_content: str = None) -> Dict[str, Any]:
        """Combined image analysis and content insights extraction to minimize API calls"""
        if not self.client:
            return {
                "description": f"Image file: {Path(image_path).name}",
                "tags": [],
                "category": "general",
                "sentiment": "neutral"
            }
        
        try:
            # Encode image to base64
            base64_image = self.encode_image_to_base64(image_path)
            if not base64_image:
                return {
                    "description": f"Image file: {Path(image_path).name}",
                    "tags": [],
                    "category": "general", 
                    "sentiment": "neutral"
                }
            
            # Determine image format
            image_format = Path(image_path).suffix.lower().replace('.', '')
            if image_format == 'jpg':
                image_format = 'jpeg'
            
            # Create comprehensive analysis prompt
            prompt = """Analyze this image and provide a JSON response with:

1. "description": Concise 1-2 sentence description of the image
2. "tags": Array of 2-4 relevant tags based on image content
3. "category": Main category (food, personal, social, work, entertainment, travel, health, shopping, general)
4. "sentiment": Emotional tone of the image (positive, negative, neutral)

"""
            
            if additional_content:
                prompt += f"\nAlso consider this additional context: {additional_content}\n"
            
            prompt += "Respond ONLY with valid JSON, no additional text."
            
            # Single API call for image + insights
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}"
                            }
                        }
                    ]
                }],
                max_tokens=200,
                temperature=0.3
            )
            
            # Parse JSON response
            response_text = response.choices[0].message.content
            if not response_text:
                raise ValueError("Empty response from LLM")
            
            response_text = response_text.strip()
            # Remove any markdown code blocks if present
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            # Validate and clean response
            if not isinstance(result.get("description"), str):
                result["description"] = f"Image file: {Path(image_path).name}"
            if not isinstance(result.get("tags"), list):
                result["tags"] = []
            if not isinstance(result.get("category"), str):
                result["category"] = "general"
            if result.get("sentiment") not in ["positive", "negative", "neutral"]:
                result["sentiment"] = "neutral"
            
            return result
            
        except Exception as e:
            print(f"Error in combined image analysis: {e}")
            return {
                "description": f"Image file: {Path(image_path).name}",
                "tags": [],
                "category": "general",
                "sentiment": "neutral"
            }


# Global LLM service instance
llm_service = LLMService()