# create_person_profile_data.py
"""Script tạo dữ liệu mẫu với Person profile đầy đủ theo schema mới."""
from graph.builder import GraphBuilder


def create_person_profile_examples():
    """Tạo dữ liệu mẫu về Person với đầy đủ relationships."""
    print("🚀 Đang tạo dữ liệu mẫu Person Profile...")
    
    builder = GraphBuilder()
    
    # Ví dụ 1: Albert Einstein
    print("\n📝 Tạo profile cho Albert Einstein...")
    builder.create_person_with_profile(
        "Albert Einstein",
        person_properties={
            "birth_date": "1879-03-14",
            "biography": "Theoretical physicist who developed the theory of relativity",
            "age": 76
        },
        born_in={
            "country": "Germany",
            "year": 1879,
            "city": "Ulm"
        },
        worked_in=[
            {
                "field": "Physics",
                "years": 50,
                "role": "Theoretical Physicist",
                "category": "Science",
                "description": "Theoretical physics and quantum mechanics"
            },
            {
                "field": "Mathematics",
                "years": 40,
                "role": "Mathematician",
                "category": "Science"
            }
        ],
        active_in=[
            {
                "era": "Early 20th Century",
                "start_year": 1900,
                "end_year": 1955,
                "description": "Period of major scientific discoveries"
            }
        ],
        achievements=[
            {
                "achievement": "Nobel Prize in Physics",
                "year": 1921,
                "description": "For services to Theoretical Physics",
                "award": "Nobel Prize",
                "significance": "Highest recognition in physics"
            },
            {
                "achievement": "Theory of Relativity",
                "year": 1905,
                "description": "Special theory of relativity",
                "significance": "Revolutionized understanding of space and time"
            }
        ],
        influenced_by=[
            {
                "person": "Max Planck",
                "influence_type": "Academic",
                "description": "Quantum theory pioneer"
            },
            {
                "person": "Isaac Newton",
                "influence_type": "Historical",
                "description": "Classical mechanics"
            }
        ],
        described_in=[
            {
                "chunk_id": "wiki_einstein_001",
                "content": "Albert Einstein was a German-born theoretical physicist...",
                "source": "Wikipedia",
                "page_title": "Albert Einstein",
                "relevance_score": 0.95
            }
        ]
    )
    
    # Ví dụ 2: Leonardo da Vinci
    print("\n📝 Tạo profile cho Leonardo da Vinci...")
    builder.create_person_with_profile(
        "Leonardo da Vinci",
        person_properties={
            "birth_date": "1452-04-15",
            "biography": "Italian Renaissance polymath",
            "age": 67
        },
        born_in={
            "country": "Italy",
            "year": 1452,
            "city": "Vinci"
        },
        worked_in=[
            {
                "field": "Art",
                "years": 50,
                "role": "Painter",
                "category": "Arts",
                "description": "Renaissance painting and sculpture"
            },
            {
                "field": "Engineering",
                "years": 40,
                "role": "Inventor",
                "category": "Science",
                "description": "Mechanical engineering and inventions"
            },
            {
                "field": "Science",
                "years": 45,
                "role": "Scientist",
                "category": "Science",
                "description": "Anatomy, botany, and physics"
            }
        ],
        active_in=[
            {
                "era": "Renaissance",
                "start_year": 1450,
                "end_year": 1519,
                "description": "Italian Renaissance period"
            }
        ],
        achievements=[
            {
                "achievement": "Mona Lisa",
                "year": 1503,
                "description": "Most famous painting in the world",
                "significance": "Cultural icon"
            },
            {
                "achievement": "The Last Supper",
                "year": 1495,
                "description": "Famous mural painting",
                "significance": "Religious art masterpiece"
            }
        ],
        influenced_by=[
            {
                "person": "Andrea del Verrocchio",
                "influence_type": "Mentor",
                "description": "Master painter and sculptor"
            }
        ],
        described_in=[
            {
                "chunk_id": "wiki_davinci_001",
                "content": "Leonardo da Vinci was an Italian polymath...",
                "source": "Wikipedia",
                "page_title": "Leonardo da Vinci",
                "relevance_score": 0.92
            }
        ]
    )
    
    # Ví dụ 3: Steve Jobs
    print("\n📝 Tạo profile cho Steve Jobs...")
    builder.create_person_with_profile(
        "Steve Jobs",
        person_properties={
            "birth_date": "1955-02-24",
            "biography": "Co-founder of Apple Inc.",
            "age": 56
        },
        born_in={
            "country": "United States",
            "year": 1955,
            "city": "San Francisco"
        },
        worked_in=[
            {
                "field": "Technology",
                "years": 35,
                "role": "CEO",
                "category": "Business",
                "description": "Consumer electronics and software"
            },
            {
                "field": "Design",
                "years": 30,
                "role": "Designer",
                "category": "Arts",
                "description": "Product design and user experience"
            }
        ],
        active_in=[
            {
                "era": "Information Age",
                "start_year": 1970,
                "end_year": 2011,
                "description": "Digital revolution era"
            }
        ],
        achievements=[
            {
                "achievement": "Co-founded Apple Inc.",
                "year": 1976,
                "description": "Revolutionary technology company",
                "significance": "Changed personal computing"
            },
            {
                "achievement": "iPhone",
                "year": 2007,
                "description": "Revolutionary smartphone",
                "significance": "Transformed mobile industry"
            }
        ],
        influenced_by=[
            {
                "person": "Steve Wozniak",
                "influence_type": "Collaborator",
                "description": "Co-founder and technical partner"
            }
        ],
        companies_founded=[
            {
                "company": "Apple Inc.",
                "year": 1976,
                "industry": "Technology"
            },
            {
                "company": "NeXT",
                "year": 1985,
                "industry": "Technology"
            }
        ],
        described_in=[
            {
                "chunk_id": "wiki_jobs_001",
                "content": "Steve Jobs was an American business magnate...",
                "source": "Wikipedia",
                "page_title": "Steve Jobs",
                "relevance_score": 0.90
            }
        ]
    )
    
    print("\n✅ Dữ liệu mẫu đã được tạo thành công!")
    print("\n📊 Dữ liệu bao gồm:")
    print("  - 3 Person nodes: Albert Einstein, Leonardo da Vinci, Steve Jobs")
    print("  - Multiple Country, Field, Era, Achievement nodes")
    print("  - Relationships: BORN_IN, WORKED_IN, ACTIVE_IN, ACHIEVED, INFLUENCED_BY, DESCRIBED_IN, FOUNDED")
    print("\n💡 Bây giờ bạn có thể hỏi:")
    print("  - 'Albert Einstein sinh ở đâu?'")
    print("  - 'Leonardo da Vinci làm việc trong lĩnh vực nào?'")
    print("  - 'Steve Jobs đã đạt được thành tựu gì?'")
    print("  - 'Ai đã ảnh hưởng đến Albert Einstein?'")
    print("  - 'Cho tôi biết về Albert Einstein' (full profile)")


if __name__ == "__main__":
    try:
        create_person_profile_examples()
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        print("\n🔍 Kiểm tra:")
        print("  1. Neo4j đang chạy chưa?")
        print("  2. config/secrets.env đã được cấu hình đúng chưa?")
        print("  3. Kết nối Neo4j có thành công không?")
