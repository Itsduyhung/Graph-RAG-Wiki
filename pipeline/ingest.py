# pipeline/ingest.py
"""Data ingestion pipeline: raw data → processed → graph."""
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from graph.builder import GraphBuilder
from graph.storage import GraphDB


class DataIngestionPipeline:
    """Pipeline for ingesting data into the knowledge graph."""
    
    def __init__(self, graph_db: GraphDB = None):
        self.graph_db = graph_db or GraphDB()
        self.graph_builder = GraphBuilder(graph_db=self.graph_db)
        self.raw_data_dir = Path("data/raw")
        self.processed_data_dir = Path("data/processed")
    
    def ingest_from_file(self, file_path: str, file_type: str = "auto") -> Dict[str, Any]:
        """
        Ingest data from a file.
        
        Args:
            file_path: Path to input file
            file_type: Type of file ('pdf', 'txt', 'csv', 'json', 'auto')
            
        Returns:
            Dictionary with ingestion results
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if file_type == "auto":
            file_type = file_path.suffix[1:].lower()  # Remove dot
        
        # Process file based on type
        processed_data = self._process_file(file_path, file_type)
        
        # Build graph from processed data
        result = self.graph_builder.build_from_data(processed_data)
        
        return {
            "status": "success",
            "file": str(file_path),
            "nodes_created": result.get("nodes_created", 0),
            "relationships_created": result.get("relationships_created", 0),
            "total": result.get("total", 0)
        }
    
    def ingest_from_directory(self, directory: str, file_types: List[str] = None) -> Dict[str, Any]:
        """
        Ingest all files from a directory.
        
        Args:
            directory: Directory path
            file_types: List of file extensions to process (e.g., ['pdf', 'txt'])
            
        Returns:
            Dictionary with ingestion results
        """
        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        file_types = file_types or ["pdf", "txt", "csv", "json", "docx"]
        results = []
        
        for file_path in directory.iterdir():
            if file_path.is_file():
                file_ext = file_path.suffix[1:].lower()
                if file_ext in file_types:
                    try:
                        result = self.ingest_from_file(file_path, file_ext)
                        results.append(result)
                    except Exception as e:
                        results.append({
                            "status": "error",
                            "file": str(file_path),
                            "error": str(e)
                        })
        
        return {
            "status": "completed",
            "files_processed": len(results),
            "results": results
        }
    
    def _process_file(self, file_path: Path, file_type: str) -> List[Dict[str, Any]]:
        """
        Process a file and extract structured data.
        
        Args:
            file_path: Path to file
            file_type: Type of file
            
        Returns:
            List of structured data dictionaries
        """
        # TODO: Implement file processing logic
        # This is a placeholder - actual implementation would:
        # - Parse PDFs, Word docs, etc.
        # - Extract entities and relationships
        # - Return structured data
        
        if file_type == "json":
            import json
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return [data]
        
        elif file_type == "txt":
            # Simple text processing - extract entities using regex or LLM
            # For now, return empty list
            return []
        
        elif file_type == "csv":
            import csv
            data = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Transform CSV row to graph structure
                    # This is a placeholder
                    data.append(row)
            return data
        
        else:
            # For other file types (PDF, DOCX), would need specialized libraries
            # Placeholder for now
            return []
    
    def ingest_from_data(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ingest pre-processed structured data directly.
        
        Args:
            data: List of structured data dictionaries
            
        Returns:
            Dictionary with ingestion results
        """
        result = self.graph_builder.build_from_data(data)
        
        return {
            "status": "success",
            "nodes_created": result.get("nodes_created", 0),
            "relationships_created": result.get("relationships_created", 0),
            "total": result.get("total", 0)
        }

