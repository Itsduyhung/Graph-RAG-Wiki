"""
Generate embeddings cho Neo4j nodes.
Dùng bge-m3 để tạo vector embeddings.
"""
from graph.storage import GraphDB
from graph.search import SemanticSearcher
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_embeddings(
    node_types: list = None,
    text_properties: list = None,
    batch_size: int = 100
):
    """
    Generate embeddings cho các nodes trong Neo4j.

    Args:
        node_types: Danh sách node types cần generate (mặc định: Person, Name, Dynasty)
        text_properties: Properties dùng để tạo text cho embedding
        batch_size: Số nodes xử lý mỗi lần
    """
    if node_types is None:
        node_types = ["Person", "Name", "Dynasty", "Achievement", "Event", "Era"]

    if text_properties is None:
        text_properties = {
            "Person": ["name", "biography"],
            "Name": ["value"],
            "Dynasty": ["name", "description"],
            "Achievement": ["name", "description"],
            "Event": ["name", "description"],
            "Era": ["name", "description"]
        }

    graph_db = GraphDB()
    semantic = SemanticSearcher(graph_db=graph_db, embedding_model="BAAI/bge-m3")

    for node_type in node_types:
        logger.info(f"Processing {node_type}...")

        props = text_properties.get(node_type, ["name"])

        with graph_db.driver.session(database=graph_db.database) as session:
            # Lấy tất cả nodes không có embedding
            result = session.run(f"""
                MATCH (n:{node_type})
                WHERE n.embedding IS NULL
                RETURN id(n) as node_id, n
                LIMIT $limit
            """, limit=batch_size)

            count = 0
            for record in result:
                node_id = record["node_id"]
                node = record["n"]

                # Tạo text từ properties
                texts = []
                for prop in props:
                    val = node.get(prop)
                    if val:
                        texts.append(str(val))

                text = " | ".join(texts)
                if not text:
                    continue

                # Generate embedding
                try:
                    embedding = semantic.model.encode(text).tolist()

                    # Update node
                    session.run("""
                        MATCH (n) WHERE id(n) = $node_id
                        SET n.embedding = $embedding
                    """, node_id=node_id, embedding=embedding)

                    count += 1
                    logger.info(f"  Updated {node_type} {node_id}: {text[:50]}...")

                except Exception as e:
                    logger.error(f"  Error: {e}")

            logger.info(f"Updated {count} {node_type} nodes")


def create_vector_indexes():
    """Tạo vector indexes trong Neo4j."""
    graph_db = GraphDB()

    indexes = [
        ("Person", 1024),
        ("Name", 1024),
        ("Dynasty", 1024),
        ("Achievement", 1024),
        ("Event", 1024),
        ("Era", 1024),
    ]

    with graph_db.driver.session() as session:
        for node_type, dim in indexes:
            index_name = f"{node_type}VectorIndex"

            # Kiểm tra index đã tồn tại chưa
            result = session.run("SHOW INDEXES")
            existing = [r["name"] for r in result]

            if index_name not in existing:
                cypher = f"""
                    CREATE VECTOR INDEX {index_name}
                    FOR (n:{node_type})
                    ON n.embedding
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {dim},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                """
                session.run(cypher)
                logger.info(f"Created index: {index_name}")
            else:
                logger.info(f"Index already exists: {index_name}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate embeddings for Neo4j")
    parser.add_argument("--create-indexes", action="store_true", help="Create vector indexes first")
    parser.add_argument("--node-types", nargs="+", default=["Person", "Name", "Dynasty"],
                        help="Node types to process")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size")

    args = parser.parse_args()

    if args.create_indexes:
        logger.info("Creating vector indexes...")
        create_vector_indexes()

    logger.info(f"Generating embeddings for: {args.node_types}")
    generate_embeddings(
        node_types=args.node_types,
        batch_size=args.batch_size
    )
