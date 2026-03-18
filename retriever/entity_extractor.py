# retriever/entity_extractor.py
"""Extract entities and intent from user questions."""
import json
from typing import Dict, Any, List, Optional
from llm.llm_client import call_llm
from llm.prompt_templates import INTENT_PROMPT, ENTITY_EXTRACTION_PROMPT


class EntityExtractor:
    """Extract entities and relationships from natural language queries - sử dụng Ollama."""
    
    def __init__(self, model: Optional[str] = None):
        """
        Initialize entity extractor.
        
        Args:
            model: Tên model Ollama (mặc định từ env OLLAMA_MODEL)
        """
        self.model = model
    
    def extract_intent(self, question: str, temperature: Optional[float] = 0.3) -> Optional[Dict[str, Any]]:
        """
        Extract structured intent from user question.
        
        Args:
            question: User question
            temperature: Temperature cho LLM (thấp hơn để có kết quả JSON ổn định)
            
        Returns:
            Dictionary with intent and extracted entities, or None if extraction fails
        """
        # Escape { and } in question to avoid format string errors
        escaped_question = question.replace("{", "{{").replace("}", "}}")
        prompt = INTENT_PROMPT.format(question=escaped_question)
        
        try:
            response = call_llm(prompt, model=self.model, temperature=temperature)
            # Try to parse JSON from response
            intent = json.loads(response)
            return intent
        except json.JSONDecodeError:
            # Try to extract JSON from text response
            try:
                # Look for JSON block in response
                start = response.find('{')
                end = response.rfind('}') + 1
                if start >= 0 and end > start:
                    intent = json.loads(response[start:end])
                    return intent
            except:
                pass
        except Exception as e:
            print(f"Error extracting intent: {e}")
        
        return None
    
    def extract_entities(self, text: str, temperature: Optional[float] = 0.3) -> List[Dict[str, Any]]:
        """
        Extract entities from text.
        
        Args:
            text: Input text
            temperature: Temperature cho LLM
        
        Returns:
            List of extracted entities with type, name, and confidence
        """
        # Escape { and } in text to avoid format string errors
        escaped_text = text.replace("{", "{{").replace("}", "}}")
        prompt = ENTITY_EXTRACTION_PROMPT.format(text=escaped_text)
        
        try:
            response = call_llm(prompt, model=self.model, temperature=temperature)
            entities = json.loads(response)
            return entities if isinstance(entities, list) else []
        except (json.JSONDecodeError, Exception) as e:
            print(f"Error extracting entities: {e}")
            return []

