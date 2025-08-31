import hashlib
import os
import requests
from pathlib import Path
from typing import Dict, Optional
import mimetypes
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv
from io import BytesIO

load_dotenv()


class MediaProcessor:
    def __init__(self, media_dir: str = "./media"):
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(exist_ok=True)
        (self.media_dir / "images").mkdir(exist_ok=True)
        (self.media_dir / "audio").mkdir(exist_ok=True)
        (self.media_dir / "transcripts").mkdir(exist_ok=True)
        
        # Initialize ElevenLabs client for transcription
        self.elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    
    def download_media(self, media_url: str, twilio_auth: tuple) -> bytes:
        """Download media from Twilio URL"""
        response = requests.get(media_url, auth=twilio_auth)
        response.raise_for_status()
        return response.content
    
    def get_content_hash(self, content: bytes) -> str:
        """Generate SHA256 hash for content"""
        return hashlib.sha256(content).hexdigest()
    
    def get_file_extension(self, media_url: str, content_type: str = None) -> str:
        """Determine file extension from URL or content type"""
        if content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext:
                return ext
        
        # Fallback to URL extension
        path = Path(media_url)
        return path.suffix if path.suffix else '.bin'
    
    def save_media_file(self, content: bytes, content_hash: str, media_type: str, 
                       file_extension: str) -> str:
        """Save media file to appropriate directory"""
        if media_type == "image":
            subdir = "images"
        elif media_type == "audio":
            subdir = "audio"
        else:
            subdir = "audio"  # Default for unknown types
        
        file_path = self.media_dir / subdir / f"{content_hash}{file_extension}"
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        return str(file_path)
    
    def transcribe_audio(self, audio_file_path: str) -> Optional[str]:
        """Transcribe audio file using ElevenLabs Speech-to-Text"""
        try:
            if not self.elevenlabs_client:
                print("ElevenLabs client not available")
                return f"[Audio file: {os.path.basename(audio_file_path)}]"
            
            # Read the audio file
            with open(audio_file_path, "rb") as audio_file:
                audio_data = BytesIO(audio_file.read())
            
            # Use ElevenLabs speech-to-text API
            transcription = self.elevenlabs_client.speech_to_text.convert(
                file=audio_data,
                model_id="scribe_v1"  # Currently the only supported model
            )
            
            # Extract just the text from the transcription response
            if hasattr(transcription, 'text'):
                return transcription.text.strip()
            elif isinstance(transcription, dict) and 'text' in transcription:
                return transcription['text'].strip()
            elif isinstance(transcription, str):
                return transcription.strip()
            else:
                # Try to extract text from complex response
                text_content = str(transcription)
                return text_content[:500] if text_content else None
                
        except Exception as e:
            print(f"Error transcribing audio with ElevenLabs: {e}")
            # Fallback to filename-based description
            return f"[Voice message from {os.path.basename(audio_file_path)}]"
    
    def process_media(self, media_url: str, message_type: str, twilio_auth: tuple, 
                     content_type: str = None) -> Dict[str, str]:
        """
        Process media file: download, deduplicate, and transcribe if needed
        
        Returns:
            Dict with keys: file_path, content_hash, transcript (if audio)
        """
        try:
            # Download media content
            content = self.download_media(media_url, twilio_auth)
            content_hash = self.get_content_hash(content)
            
            # Check for existing file (deduplication)
            file_extension = self.get_file_extension(media_url, content_type)
            
            if message_type == "image":
                subdir = "images"
            elif message_type == "audio":
                subdir = "audio"
            else:
                subdir = "audio"
            
            expected_path = self.media_dir / subdir / f"{content_hash}{file_extension}"
            
            # If file doesn't exist, save it
            if not expected_path.exists():
                file_path = self.save_media_file(content, content_hash, message_type, file_extension)
            else:
                file_path = str(expected_path)
            
            result = {
                "file_path": file_path,
                "content_hash": content_hash,
                "file_size": len(content),
                "file_extension": file_extension
            }
            
            # Transcribe audio files
            if message_type == "audio":
                transcript = self.transcribe_audio(file_path)
                result["transcript"] = transcript
                
                # Save transcript to separate file
                if transcript:
                    transcript_path = self.media_dir / "transcripts" / f"{content_hash}.txt"
                    with open(transcript_path, "w") as f:
                        f.write(transcript)
                    result["transcript_path"] = str(transcript_path)
            
            return result
            
        except Exception as e:
            print(f"Error processing media: {e}")
            return {
                "error": str(e),
                "file_path": None,
                "content_hash": None
            }


