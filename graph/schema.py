# graph/schema.py
"""Graph schema definitions for nodes and relationships."""

# Node Types
PERSON = "Person"
COMPANY = "Company"
COUNTRY = "Country"
FIELD = "Field"
ERA = "Era"
ACHIEVEMENT = "Achievement"
WIKICHUNK = "WikiChunk"
EVENT = "Event"
TIMEPOINT = "TimePoint"
ROLE = "Role"
DYNASTY = "Dynasty"

# Relationship Types
FOUNDED = "FOUNDED"
WORKS_AT = "WORKS_AT"
OWNS = "OWNS"
BORN_IN = "BORN_IN"
WORKED_IN = "WORKED_IN"
ACTIVE_IN = "ACTIVE_IN"
ACHIEVED = "ACHIEVED"
INFLUENCED_BY = "INFLUENCED_BY"
DESCRIBED_IN = "DESCRIBED_IN"
CHILD_OF = "CHILD_OF"
PARTICIPATED_IN = "PARTICIPATED_IN"
BORN_AT = "BORN_AT"
DIED_AT = "DIED_AT"
HAPPENED_AT = "HAPPENED_AT"
HAS_ROLE = "HAS_ROLE"
BELONGS_TO_DYNASTY = "BELONGS_TO_DYNASTY"

# Schema definition
GRAPH_SCHEMA = {
    "nodes": {
        PERSON: {
            "properties": [
                "name", "age", "email",
                "birth_date", "birth_year",
                "death_date", "death_year",
                "biography", "role",
                "reign_start_year", "reign_end_year",
                "aliases", "other_names"
            ],
            "description": "Represents a person entity (historical figure, etc.)"
        },
        COMPANY: {
            "properties": ["name", "industry", "founded_year"],
            "description": "Represents a company entity"
        },
        COUNTRY: {
            "properties": ["name", "code", "region"],
            "description": "Represents a country entity"
        },
        FIELD: {
            "properties": ["name", "category", "description"],
            "description": "Represents a field of work or study"
        },
        ERA: {
            "properties": ["name", "start_year", "end_year", "description"],
            "description": "Represents a historical era or time period"
        },
        ACHIEVEMENT: {
            "properties": ["name", "year", "description", "award"],
            "description": "Represents an achievement or accomplishment"
        },
        WIKICHUNK: {
            "properties": ["content", "source", "chunk_id", "page_title"],
            "description": "Represents a chunk of text from Wikipedia or other sources"
        },
        EVENT: {
            "properties": ["name", "year", "description", "significance"],
            "description": "Represents a historical event or milestone"
        },
        TIMEPOINT: {
            "properties": ["label", "year", "month", "day"],
            "description": "Represents a time point (year/month/day) for timelines"
        },
        ROLE: {
            "properties": ["name", "category", "description"],
            "description": "Represents a role/title (e.g., King, Poet, General)"
        },
        DYNASTY: {
            "properties": ["name", "start_year", "end_year", "description"],
            "description": "Represents a dynasty/regime (e.g., Tiền Lê, Trần, Nguyễn)"
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
        },
        BORN_IN: {
            "from": PERSON,
            "to": COUNTRY,
            "properties": ["year", "city"],
            "description": "Person was born in Country"
        },
        WORKED_IN: {
            "from": PERSON,
            "to": FIELD,
            "properties": ["years", "role"],
            "description": "Person worked in Field"
        },
        ACTIVE_IN: {
            "from": PERSON,
            "to": ERA,
            "properties": ["start_year", "end_year"],
            "description": "Person was active in Era"
        },
        ACHIEVED: {
            "from": PERSON,
            "to": ACHIEVEMENT,
            "properties": ["year", "significance"],
            "description": "Person achieved Achievement"
        },
        INFLUENCED_BY: {
            "from": PERSON,
            "to": PERSON,
            "properties": ["influence_type", "description"],
            "description": "Person was influenced by another Person"
        },
        DESCRIBED_IN: {
            "from": PERSON,
            "to": WIKICHUNK,
            "properties": ["relevance_score"],
            "description": "Person is described in WikiChunk"
        },
        CHILD_OF: {
            "from": PERSON,
            "to": PERSON,
            "properties": ["relation_type"],
            "description": "Person is the child of another Person (parent-child relationship)"
        },
        PARTICIPATED_IN: {
            "from": PERSON,
            "to": EVENT,
            "properties": ["year", "role", "description", "significance"],
            "description": "Person participated in or is strongly associated with an Event"
        },
        BORN_AT: {
            "from": PERSON,
            "to": TIMEPOINT,
            "properties": [],
            "description": "Person was born at a TimePoint"
        },
        DIED_AT: {
            "from": PERSON,
            "to": TIMEPOINT,
            "properties": [],
            "description": "Person died at a TimePoint"
        },
        HAPPENED_AT: {
            "from": EVENT,
            "to": TIMEPOINT,
            "properties": [],
            "description": "Event happened at a TimePoint"
        },
        HAS_ROLE: {
            "from": PERSON,
            "to": ROLE,
            "properties": ["start_year", "end_year"],
            "description": "Person has a Role/Title"
        },
        BELONGS_TO_DYNASTY: {
            "from": PERSON,
            "to": DYNASTY,
            "properties": ["start_year", "end_year"],
            "description": "Person belongs to a Dynasty"
        }
    }
}


