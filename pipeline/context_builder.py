# pipeline/context_builder.py
"""Build context from retrieved graph data."""
from typing import Dict, Any, List


class ContextBuilder:
    """Build context strings from retrieved graph data."""
    
    @staticmethod
    def build_context_from_results(results: Dict[str, Any]) -> str:
        """
        Build context string from graph retrieval results.
        
        Args:
            results: Dictionary with retrieval results
            
        Returns:
            Formatted context string
        """
        context_parts = []
        
        # Company and founder information
        if "company" in results and "founders" in results:
            company = results["company"]
            founders = results["founders"]
            
            if founders:
                context_parts.append(f"Company: {company}")
                context_parts.append(f"Founders: {', '.join(founders)}")
            else:
                context_parts.append(f"Company: {company} (no founders found)")
        
        # Person and companies information
        if "person" in results and "companies_founded" in results:
            person = results["person"]
            companies = results["companies_founded"]
            
            if companies:
                context_parts.append(f"Person: {person}")
                context_parts.append(f"Companies Founded: {', '.join(companies)}")
            else:
                context_parts.append(f"Person: {person} (no companies found)")
        
        # Relationship information
        if "source" in results and "targets" in results:
            source = results["source"]
            relationship = results.get("relationship", "")
            targets = results["targets"]
            
            target_names = [t.get("target_name", "") for t in targets if t.get("target_name")]
            if target_names:
                context_parts.append(f"{source} {relationship} {', '.join(target_names)}")
        
        return "\n".join(context_parts)
    
    @staticmethod
    def build_context_from_subgraph(subgraph: List[Dict]) -> str:
        """
        Build context from subgraph results.
        
        Args:
            subgraph: List of subgraph records
            
        Returns:
            Formatted context string
        """
        if not subgraph:
            return ""
        
        context_parts = []
        entities = set()
        
        for record in subgraph:
            # Extract entity information from path records
            # This is simplified - actual implementation would parse Neo4j path records
            if "n" in record:
                entity = record["n"]
                entities.add(str(entity))
            if "connected" in record:
                connected = record["connected"]
                entities.add(str(connected))
        
        if entities:
            context_parts.append(f"Related entities: {', '.join(sorted(entities))}")
        
        return "\n".join(context_parts)
    
    @staticmethod
    def combine_contexts(contexts: List[str]) -> str:
        """
        Combine multiple context strings.
        
        Args:
            contexts: List of context strings
            
        Returns:
            Combined context string
        """
        # Filter out empty contexts
        non_empty = [c for c in contexts if c.strip()]
        
        if not non_empty:
            return ""
        
        # Join with separator
        return "\n\n".join(non_empty)


