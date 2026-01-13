# graph/schema.py
"""Graph schema definitions for nodes and relationships."""

# Node Types
PERSON = "Person"
COMPANY = "Company"

# Relationship Types
FOUNDED = "FOUNDED"
WORKS_AT = "WORKS_AT"
OWNS = "OWNS"

# Schema definition
GRAPH_SCHEMA = {
    "nodes": {
        PERSON: {
            "properties": ["name", "age", "email"],
            "description": "Represents a person entity"
        },
        COMPANY: {
            "properties": ["name", "industry", "founded_year"],
            "description": "Represents a company entity"
        }
    },
    "relationships": {
        FOUNDED: {
            "from": PERSON,
            "to": COMPANY,
            "properties": ["year"],
            "description": "Person founded Company"
        },
        WORKS_AT: {
            "from": PERSON,
            "to": COMPANY,
            "properties": ["role", "start_date"],
            "description": "Person works at Company"
        },
        OWNS: {
            "from": PERSON,
            "to": COMPANY,
            "properties": ["share_percentage"],
            "description": "Person owns Company"
        }
    }
}


