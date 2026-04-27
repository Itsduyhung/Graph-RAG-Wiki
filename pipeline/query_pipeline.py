# pipeline/query_pipeline.py

"""
Query Pipeline - DB-driven retrieval + LLM precision filtering

Flow:
1. QUERY UNDERSTANDING (Rule-based, nhẹ)
2. CANDIDATE RETRIEVAL (DB-driven 100%)
   - Fulltext search (primary)
   - Soft matching (fallback)
   - Vector search (fallback)
3. GRAPH EXPANSION (DB)
4. CONTEXT FILTERING (LLM - CHỈ filter, KHÔNG search)
5. ANSWER GENERATION (LLM)
"""

import time
import json
import re
import os
from typing import Dict, Any, Optional, List, Tuple
from graph.storage import GraphDB
from llm.answer_generator import AnswerGenerator
from llm.llm_client import call_llm
from pipeline.query import expansion as query_expansion
from pipeline.query import formatting as query_formatting
from pipeline.query import handlers as query_handlers
from pipeline.query import retrieval as query_retrieval
from pipeline.query import search as query_search
from pipeline.query import understanding as query_understanding

# Vietnamese word segmentation
try:
    import underthesea
    WORD_SEG_AVAILABLE = True
except ImportError:
    WORD_SEG_AVAILABLE = False

# Semantic search
try:
    from sentence_transformers import SentenceTransformer
    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False


# ============================================================================
# NAME ALIAS PATTERNS - Tìm alias trước, ghép với Person
# ============================================================================
NAME_PATTERNS = {
    "tên thật": ["birth_name", "real_name", "tên thật", "tên khai sinh"],
    "tên khai sinh": ["birth_name", "real_name", "tên thật"],
    "tên húy": ["temple_name", "tên húy"],
    "tên gốc": ["original_name", "birth_name"],
    "niên hiệu": ["regnal_name", "niên hiệu"],
    "tên gọi khác": ["alias", "other_name"],
    "biệt danh": ["nickname", "alias"],
    "nêu đầy đủ": ["full_name", "name"],
    # Quan hệ gia đình
    "con của": ["PARENT_OF"],
    "cha của": ["PARENT_OF"],
    "mẹ của": ["PARENT_OF"],
    "vợ": ["SPOUSE_OF"],
    "chồng": ["SPOUSE_OF"],
}

# ============================================================================
# EVENT SYNONYMS - DB-driven synonyms cho events
# ============================================================================
# Cấu trúc DB: (:Word {name: "đăng quang"})-[:SYNONYM]->(:Word {name: "lên ngôi"})
EVENT_SYNONYM_GROUPS = [
    # Đăng quang / Lên ngôi
    ["đăng quang", "lên ngôi", "đăng cơ", "đăng vị", "thái tọa", "lên làm vua", "đăng hoàng"],
    # Sinh / Ra đời
    ["sinh", "ra đời", "hạ sinh", "chào đời", "ra mắt"],
    # Mất / Qua đời
    ["mất", "qua đời", "từ trần", "tịch", "băng hà", "thoái vị"],
    # Kết hôn
    ["kết hôn", "cưới", "thành hôn", "lấy vợ", "lấy chồng"],
    # Bổ nhiệm
    ["bổ nhiệm", "phong chức", "thăng chức", "lập quan"],
]


class QueryPipeline:
    """Query pipeline - DB-driven recall + LLM precision."""

    # Cache schema + synonyms
    _schema_cache: Optional[str] = None
    _synonym_cache: Dict[str, List[str]] = {}  # word -> list of synonyms
    EVENT_SYNONYM_GROUPS = EVENT_SYNONYM_GROUPS

    # Intent keywords mapping (rule-based)
    INTENT_MAPPING = {
        # Tên gọi properties - QUAN TRỌNG cho "tên thật/birth_name"
        "tên thật": "birth_name",
        "tên khai sinh": "birth_name",
        "tên húy": "temple_name",
        "tên gốc": "original_name",
        "niên hiệu": "regnal_name",
        "tên chính": "name",
        "tên gọi khác": "alias",
        "biệt danh": "nickname",
        "nêu đầy đủ": "full_name",
        # Relationship intents
        "đánh": "ACHIEVED",
        "chỉ huy": "COMMANDED",
        "sáng lập": "FOUNDED",
        "làm": "PARTICIPATED_IN",
        "gây ra": "CAUSED",
        "thuộc": "BELONGS_TO",
        "con của": "PARENT_OF",
        "cha của": "PARENT_OF",
        "kế nhiệm": "SUCCESSOR_OF",
        "tiền nhiệm": "PREDECESSOR_OF",
        # Alias patterns
        "còn gọi": "alias",
        "cũng gọi": "alias",
        "hay còn": "alias",
        "bí danh": "nickname",
        "tước hiệu": "title",
        "tước vị": "title",
        "tự xưng": "title",
        "tự xưng là": "title",
        "hiệu gì": "title",
        "tên hiệu": "title",
        "hoàng hiệu": "title",
        "đế hiệu": "title",
    }

    def __init__(self, graph_db: GraphDB = None, model: str = None):
        self.graph_db = graph_db or GraphDB()
        self.model = model
        self.answer_generator = AnswerGenerator(model=model)

        # Semantic model (lazy load)
        self._semantic_model = None
        self._semantic_model_name = "BAAI/bge-m3"

    # =========================================================================
    # 1. QUERY UNDERSTANDING (Rule-based, nhẹ)
    # =========================================================================
    # INTENT & KEYWORD MAPPING
    # =========================================================================

    # Mapping từ khóa → relationship type
    INTENT_MAPPING = {
        # Tên gọi properties
        "tên thật": "real_name",
        "tên khai sinh": "birth_name",
        "tên húy": "temple_name",
        "tên gốc": "original_name",
        "niên hiệu": "regnal_name",
        "tên chính": "name",
        "tên gọi khác": "alias",
        "biệt danh": "nickname",
        "nêu đầy đủ": "full_name",
        # === NEW: Marriage/Spouse intents ===
        "vợ": "SPOUSE_OF",
        "chồng": "SPOUSE_OF",
        "bạn đời": "SPOUSE_OF",
        "vợ chồng": "SPOUSE_OF",
        "kết hôn": "SPOUSE_OF",
        "cưới": "SPOUSE_OF",
        "lấy vợ": "SPOUSE_OF",
        "lấy chồng": "SPOUSE_OF",
        "thành hôn": "SPOUSE_OF",
        "hôn nhân": "SPOUSE_OF",
        "tái hôn": "SPOUSE_OF",
        "tái giá": "SPOUSE_OF",
        "tòng phu": "SPOUSE_OF",
        "cầu nương": "SPOUSE_OF",
        "tỷ muội": "SPOUSE_OF",
        "phụ quân": "SPOUSE_OF",
        "phu quân": "SPOUSE_OF",
        "phu nhân": "SPOUSE_OF",
        "thê tử": "SPOUSE_OF",
        "nửa kia": "SPOUSE_OF",
        
        # === NEW: Child/Children relationships ===
        # Con đẻ / Con ruột
        "con cái": "CHILD_OF",
        "con đẻ": "CHILD_OF",
        "con ruột": "CHILD_OF",
        "con em": "CHILD_OF",
        "con lệ": "CHILD_OF",
        "hậu duệ": "CHILD_OF",
        "nòi giống": "CHILD_OF",
        "dòng dõi": "CHILD_OF",
        "thế hệ sau": "CHILD_OF",
        "con cháu": "CHILD_OF",
        "huyết thống": "CHILD_OF",
        "tôi tớ": "CHILD_OF",
        "con kế": "CHILD_OF",
        "con dâu": "CHILD_OF",
        "con rể": "CHILD_OF",
        "con trai": "CHILD_OF",
        "con gái": "CHILD_OF",
        "các con": "CHILD_OF",
        "những con": "CHILD_OF",
        
        # Con nuôi / Adopted children
        "con nuôi": "ADOPTED_CHILD_OF",
        "nhận nuôi": "ADOPTED_CHILD_OF",
        "được nuôi": "ADOPTED_CHILD_OF",
        "con nhân": "ADOPTED_CHILD_OF",
        "con yêu": "ADOPTED_CHILD_OF",
        "con trai nuôi": "ADOPTED_CHILD_OF",
        "con gái nuôi": "ADOPTED_CHILD_OF",
        
        # Con dâu/rể nuôi / Foster children (contextual - only when asking about foster relationships)
        "con dâu nuôi": "FOSTER_CHILD_OF",
        "con rể nuôi": "FOSTER_CHILD_OF",
        
        # === NEW: Parent relationships (expanded) ===
        "cha mẹ": "PARENT_OF",
        "cha": "PARENT_OF",
        "mẹ": "PARENT_OF",
        "ba": "PARENT_OF",
        "má": "PARENT_OF",
        "bậc cha mẹ": "PARENT_OF",
        "bố mẹ": "PARENT_OF",
        "bố": "PARENT_OF",
        "phụ thân": "PARENT_OF",
        "mẫu thân": "PARENT_OF",
        "mẹ kế": "PARENT_OF",
        "cha kế": "PARENT_OF",
        
        # Adoptive parents (matches DB relationship type)
        "cha nuôi": "ADOPTIVE_PARENT_OF",
        "mẹ nuôi": "ADOPTIVE_PARENT_OF",
        
        # Foster/Step parents (new relationship types)
        "cha dượng": "FOSTER_PARENT_OF",
        "mẹ dượng": "FOSTER_PARENT_OF",
        
        "con của": "PARENT_OF",
        "cha của": "PARENT_OF",
        # Relationship intents
        "đánh": "ACHIEVED",
        "chỉ huy": "PARTICIPATED_IN",
        "sáng lập": "FOUNDED",
        "làm": "PARTICIPATED_IN",
        "gây ra": "CAUSED",
        "thuộc": "BELONGS_TO",
        "con của": "PARENT_OF",
        "cha của": "PARENT_OF",
        # Event-related intents
        "tham gia": "PARTICIPATED_IN",
        "thực hiện": "PERFORMED",
        "đăng quang": "PERFORMED",
        "lên ngôi": "PERFORMED",
        "phong": "PERFORMED",
        
        # === FIX: Temporal intents (QUAN TRỌNG cho query về ngày sinh/mất) ===
        # Sinh / Ra đời
        "sinh năm": "birth_date",
        "ngày sinh": "birth_date",
        "năm sinh": "birth_date",
        "sinh tháng": "birth_date",
        "ra đời": "birth_date",
        "chào đời": "birth_date",
        "hạ sinh": "birth_date",
        # Mất / Qua đời
        "mất năm": "death_date",
        "ngày mất": "death_date",
        "năm mất": "death_date",
        "mất lúc": "death_date",
        "qua đời": "death_date",
        "từ trần": "death_date",
        "băng hà": "death_date",
        "tắt thở": "death_date",
        "hưởng thọ": "death_date",
        # Location / Notable works
        "ở đâu": "location",
        "sống ở": "location",
        "lưu vong ở": "location",
        "lưu lạc ở": "location",
        "tác phẩm": "notable_works",
        "tác phẩm tiêu biểu": "notable_works",
        "các tác phẩm": "notable_works",
        "thành tựu": "achievements",
        # Burial
        "ngày chôn cất": "burial_date",
        "ngày an táng": "burial_date",
        "chôn cất năm": "burial_date",
        "an táng năm": "burial_date",
        "nơi yên nghỉ": "burial_date",
        # Lên ngôi / Đăng quang
        "lên ngôi": "reign_start",
        "đăng quang": "reign_start",
        "đăng cơ": "reign_start",
        "nhận ngôi": "reign_start",
        # Thôi ngôi / Mất ngôi
        "thoái vị": "reign_end",
        "thôi ngôi": "reign_end",
        "mất ngôi": "reign_end",
        # Successor/Predecessor
        "kế nhiệm": "SUCCESSOR_OF",
        "tiền nhiệm": "PREDECESSOR_OF",
        # === FIX: Reign-related intents ===
        "tại vị": "reign_duration",
        "tại vị bao lâu": "reign_duration",
        "tại vị bao nhiêu ngày": "reign_duration",
        "tại vị bao nhiêu năm": "reign_duration",
        "trị vì": "reign_duration",
        "trị vì bao lâu": "reign_duration",
        "trị vì bao nhiêu ngày": "reign_duration",
        "trị vì bao nhiêu năm": "reign_duration",
        "thời gian tại vị": "reign_duration",
        "thời gian trị vì": "reign_duration",
        "khoảng thời gian trị vì": "reign_duration",
        "thời lượng trị vì": "reign_duration",
        # === NEW: Personality-related intents ===
        "tính cách": "personality",
        "tính tình": "personality",
        "đặc điểm": "personality",
        "đặc điểm tính cách": "personality",
        "tính ngoài": "personality",
        "tính chất": "personality",
        "thuộc tính": "personality",
        "tính chất cá nhân": "personality",
        # === NEW: Event-related intents ===
        "sự kiện": "EVENT",
        "sự kiện ngoại giao": "TREATY",
        "hòa ước": "TREATY",
        "điều ước": "TREATY",
        "hiệp định": "TREATY",
        "bị ký kết": "TREATY",
        "ký kết": "TREATY",
        "ngoại giao": "TREATY",
        "xảy ra": "EVENT",
        "diễn ra": "EVENT",
        "được nêu": "EVENT",
        "sự kiện quân sự": "MILITARY",
        "chiến đấu": "MILITARY",
        "khởi nghĩa": "REBELLION",
        "ruhiệu": "REBELLION",
    }

    # Biến thể câu hỏi - synonym mapping (đồng nghĩa, cùng ý nghĩa)
    QUERY_VARIANTS = {
        # === Đăng quang / Lên ngôi / Hoàng đế ===
        "đăng quang": ["lên ngôi", "lên làm vua", "phong hoàng đế", "được phong làm vua", "đăng cơ", "lên ngôi hoàng đế", "được phong hoàng đế", "lên ngôi vua"],
        "lên ngôi": ["đăng quang", "đăng cơ", "lên làm vua", "phong hoàng đế", "đăng ngôi", "nhận ngôi", "tiếp nhận ngôi vua", "kế vị"],
        "phong hoàng đế": ["đăng quang", "lên ngôi", "phong vương", "được phong vương", "lên ngôi hoàng đế"],
        "hoàng đế": ["vua", "bậc đế vương", "đấng chí tôn", "nhà vua", "quân chủ"],

        # === Sinh / Mất / Qua đời ===
        "sinh": ["ra đời", "chào đời", "được sinh", "ngày sinh", "năm sinh", "sinh ra", "hạ sinh", "chào đời", "ra đời"],
        "mất": ["qua đời", "tắt thở", "băng hà", "trí thứ", "ngày mất", "năm mất", "từ trần", "quy tiên", "hóa", "hưởng thọ"],
        "qua đời": ["mất", "băng hà", "tắt thở", "trí thứ", "từ trần", "quy tiên", "hóa", "tử vong", "ngã xuống"],
        "băng hà": ["mất", "qua đời", "tắt thở", "từ trần", "quy tiên", "trí thứ"],
        "từ trần": ["mất", "qua đời", "băng hà", "quy tiên", "hóa"],

        # === Tham gia / Chỉ huy / Lãnh đạo ===
        "tham gia": ["tham dự", "có mặt", "tham gia", "tham dự", "tham gia vào", "tham dự vào", "đánh", "chiến đấu", "tham chiến"],
        "chỉ huy": ["lãnh đạo", "cầm quân", "command", "chỉ huy", "chỉ huy quân đội", "thống lĩnh", "tổng tư lệnh"],
        "lãnh đạo": ["chỉ huy", "cầm đầu", "cầm quyền", "đứng đầu", "dẫn dắt", "lãnh đạo", "điều khiển"],
        "sáng lập": ["thành lập", "lập ra", "tạo dựng", "dựng nên", "khai sinh", "khai lập", "lập nên", "tạo nên"],

        # === Chiến tranh / Trận đánh ===
        "chiến tranh": ["đánh nhau", "xung đột", "quân sự", "giặc", "đấu tranh", "nội chiến", "ngoại chiến", "chiến tranh với"],
        "trận đánh": ["trận chiến", "đánh trận", "giao chiến", "nghinh chiến", "đụng độ", "hỗn chiến"],
        "chiến thắng": ["thắng lợi", "thắng trận", "đánh bại", "đại phá", "phá tan", "quét sạch"],
        "đánh bại": ["thắng", "chiến thắng", "đại phá", "phá tan", "hạ gục", "tiêu diệt"],

        # === Thành tựu / Đạt được ===
        "thành tựu": ["đạt được", "chiến thắng", "giành được", "hoàn thành", "tạo nên", "xây dựng được", "lập nên"],
        "đạt được": ["đạt được", "hoàn thành", "hoàn thành được", "thành công", "thực hiện được", "làm được"],
        "giành được": ["đạt được", "chiếm được", "lấy được", "thu được", "có được"],
        "chiến thắng": ["thắng", "thắng lợi", "thắng trận", "đại thắng", "toàn thắng"],

        # === Vai trò / Chức vụ ===
        "chức vụ": ["vai trò", "chức", "chức vụ", "chức danh", "vị trí", "cương vị", "tước vị"],
        "vai trò": ["chức vụ", "nhiệm vụ", "vị trí", "chức", "chức danh"],
        "thủ tướng": ["tổng thống", "quốc vụ khanh", "bộ trưởng", "trưởng bộ"],
        "tổng thống": ["thủ tướng", "quốc vụ khanh", "chủ tịch", "lãnh đạo"],
        "chủ tịch": ["thủ tướng", "tổng thống", "giám đốc", "lãnh đạo", "trưởng"],

        # === Triều đại / Thời kỳ ===
        "triều đình": ["triều đại", "triều", "nhà Nguyễn", "nhà Lê", "nhà Trần", "nhà Đinh", "nhà Lý"],
        "thời kỳ": ["giai đoạn", "kỷ nguyên", "trang lịch sử", "đời", "đời nhà"],
        "nhà Nguyễn": ["triều Nguyễn", "nhà Thanh", "triều đình Nguyễn"],
        "nhà Lê": ["triều Lê", "nhà Hậu Lê", "Lê triều"],
        "nhà Trần": ["triều Trần", "Trần triều"],
        "nhà Lý": ["triều Lý", "Lý triều"],

        # === Học vấn / Tri thức ===
        "học vấn": ["học thức", "kiến thức", "bằng cấp", "học hàm", "học hành"],
        "học": ["nghiên cứu", "học tập", "đọc sách", "học hành"],
        "giáo sư": ["GS", "giảng viên", "thầy giáo", "học giả", "nhà nghiên cứu"],
        "tiến sĩ": ["TS", "PhD", "bác sĩ", "chủ tịch", "học vị"],

        # === Gia đình / Quan hệ ===
        "vợ": ["phu nhân", "thê tử", "bầu bạn", "người vợ", "bạn đời", "vợ cũ", "vợ thứ", "nửa kia", "cầu nương", "nương nương", "hoàng hậu", "thứ thác"],
        "chồng": ["phu quân", "phu nhân", "bầu bạn", "người chồng", "bạn đời", "chồng cũ", "chồng thứ", "nửa kia", "tỷ muội", "hoàng đế", "vua"],
        "kết hôn": ["cưới", "thành hôn", "lấy vợ", "lấy chồng", "kết duyên", "kết giao", "cưới vợ", "tòng phu", "tòng phu chi thể", "yên chiêu", "yên ủi"],
        "cưới": ["kết hôn", "thành hôn", "lấy vợ", "lấy chồng", "kết duyên", "kết giao", "tòng phu", "hôn sự"],
        "tái hôn": ["tái giá", "lấy lại", "cưới lại", "hôn nhân thứ hai", "cưới thêm", "lập gia đình lần thứ hai"],
        "tái giá": ["tái hôn", "lấy lại", "cưới lại", "hôn nhân thứ hai", "cưới tái", "bước vào hôn nhân lần thứ hai"],
        "hôn nhân": ["cưới", "hôn sự", "duyên số", "kết duyên", "hôn giới", "duyên nợ", "tình yêu"],
        "vợ chồng": ["hôn nhân", "danh chính", "duyên số", "bạn đời", "nửa kia", "hai người một nhà"],
        "con cái": ["con em", "hậu duệ", "nòi giống", "dòng dõi", "con đẻ", "con lệ", "con nuôi", "con kế", "con trai", "con gái", "các con", "những con"],
        "con em": ["con cái", "hậu duệ", "nòi giống", "con đẻ", "thế hệ sau", "con trai", "con gái", "con ruột"],
        "con": ["hậu duệ", "huyết thống", "đời sau", "con cháu", "nòi giống", "con đẻ", "con lệ", "con nuôi", "con kế", "con trai", "con gái"],
        "con đẻ": ["con ruột", "con em", "con trai", "con gái", "huyết thống"],
        "con ruột": ["con đẻ", "con em", "huyết thống", "nòi giống"],
        "con nuôi": ["nhận nuôi", "được nuôi", "nuôi như con", "con nhân", "con yêu", "con trai nuôi", "con gái nuôi"],
        "con lệ": ["con nuôi", "con kế", "con của vợ/chồng"],
        "con kế": ["con lệ", "con nuôi", "con cũ"],
        "con trai": ["con trai nuôi", "con trai ruột", "con trai đẻ", "quý tử", "hoàng tử"],
        "con gái": ["con gái nuôi", "con gái ruột", "con gái đẻ", "nữ công chúa", "công chúa"],
        "hậu duệ": ["con cái", "nòi giống", "dòng dõi", "thế hệ sau", "con em"],
        "nòi giống": ["dòng dõi", "huyết thống", "con em", "hậu duệ", "con cháu"],
        "dòng dõi": ["nòi giống", "huyết thống", "hậu duệ", "gia tộc"],
        
        "cha": ["phụ thân", "ông", "tổ phụ", "bố", "ba", "bố già", "tỷ phụ", "cha ruột", "cha đẻ", "cha nuôi", "cha kế"],
        "mẹ": ["mẫu thân", "bà", "tổ mẫu", "má", "u", "mẹ kế", "côi mẹ", "mẹ ruột", "mẹ đẻ", "mẹ nuôi"],
        "cha mẹ": ["bố mẹ", "cha mẹ ruột", "cha mẹ đẻ", "bậc cha mẹ", "phụ mẫu"],
        "bố mẹ": ["cha mẹ", "bố mẹ ruột", "bố mẹ đẻ", "bậc cha mẹ"],
        "bố": ["ba", "cha", "phụ thân", "bố ruột", "bố đẻ", "bố kế"],
        "mẹ kế": ["mẹ nuôi", "mẹ thứ", "mẹ sau"],
        "cha kế": ["cha nuôi", "cha thứ", "cha sau"],
        "cha nuôi": ["cha dậu", "cha thay", "người nuôi dạy"],
        "mẹ nuôi": ["mẹ thay", "mẹ dậu", "người nuôi dạy"],
        "anh em": ["đệ tử", "huynh đệ", "bằng hữu", "bạn bè", "anh chị em", "em trai", "em gái"],
        "thân": ["bạn thân", "hảo hữu", "tri kỷ", "bằng hữu", "bạn thân thích"],
        "con người": ["nhân vật", "ân nhân", "người", "cá nhân", "từng người"],

        # === Địa điểm / Nơi chốn ===
        "sinh ra": ["xuất thân", "quê quán", "bản quán", " quê", " quê hương", "nơi sinh"],
        "quê": ["quê hương", "quê quán", "bản quán", "xuất thân", "cố hương", " quê"],
        "thủ đô": ["kinh đô", "kinh thành", "hoàng thành", "trung tâm", "thủ đô"],
        "kinh đô": ["thủ đô", "kinh thành", "hoàng thành", "thủ phủ"],

        # === Khai phá / Xây dựng ===
        "khai phá": ["mở mang", "xây dựng", "kiến thiết", "phát triển", "xây dựng nên"],
        "mở mang": ["khai phá", "mở rộng", "phát triển", "kiến thiết"],
        "xây dựng": ["kiến thiết", "xây dựng nên", "tạo dựng", "kiến tạo"],

        # === Cải cách / Đổi mới ===
        "cải cách": ["đổi mới", "cải lương", "cải tổ", "cải biến", "đổi mới"],
        "đổi mới": ["cải cách", "cải tổ", "đổi mới sáng tạo", "cải biến"],
        "chính sách": ["đường lối", "quyết sách", "chủ trương", "pháp lệnh"],

        # === Nhượng bộ / Ký kết ===
        "ký kết": ["ký", "ký hợp đồng", "ký hiệp ước", "đặt bút", "làm hợp đồng"],
        "nhượng bộ": ["nhượng", "nhả", "bỏ", "từ bỏ", "buông"],
        "hiệp ước": ["hòa ước", "điều ước", "hiệp định", "thỏa ước"],

        # === Tham nhũng / Tội lỗi ===
        "tham nhũng": ["hối lộ", "tham ô", "tham lam", "ăn hối lộ"],
        "lưu đày": ["đày", "trục xuất", "lưu vong", "bị lưu đày", "đi đày"],
        "bị bắt": ["bị giam", "giam giữ", "tù đày", "cầm tù"],

        # === Từ trị / Bình định ===
        "từ trị": ["đô hộ", "cai trị", "thống trị", "cai quản", "quản lý"],
        "đô hộ": ["từ trị", "thống trị", "cai trị", "đô thống"],
        "bình định": ["dẹp loạn", "thu phục", "thống nhất", "bình", "bình定"],

        # === Tựu trung / Khai hội ===
        "tựu trung": ["tụ họp", "họp mặt", "tề tựu", "tụ hội"],
        "khai hội": ["mở cuộc họp", "tổ chức", "triệu tập", "họp báo"],
        "tổ chức": ["sắp xếp", "thiết lập", "thành lập", "xây dựng"],

        # === Công nhận / Phủ nhận ===
        "công nhận": ["thừa nhận", "công khai thừa nhận", "công nhận là"],
        "phủ nhận": ["bác bỏ", "phủ định", "phủ nhận", "bác bỏ", "phản đối"],
    }

    # =========================================================================

    def _understand_query(self, question: str) -> Dict[str, Any]:
        return query_understanding.understand_query(self, question)

    # =========================================================================
    # SYNONYM MANAGEMENT - DB-driven synonyms
    # =========================================================================

    def _load_synonyms_from_db(self) -> Dict[str, List[str]]:
        return query_understanding.load_synonyms_from_db(self)

    def _build_synonym_cache_from_groups(self) -> Dict[str, List[str]]:
        return query_understanding.build_synonym_cache_from_groups(self)

    def _get_synonyms(self, word: str) -> List[str]:
        return query_understanding.get_synonyms(self, word)

    def _expand_query_with_synonyms(self, keywords: List[str]) -> List[str]:
        return query_understanding.expand_query_with_synonyms(self, keywords)

    def _extract_entity(self, question: str) -> str:
        return query_understanding.extract_entity(self, question)

    def _find_person_names_in_question(self, question: str) -> List[str]:
        return query_understanding.find_person_names_in_question(self, question)

    def _extract_keywords(self, question: str) -> List[str]:
        return query_understanding.extract_keywords(question)

    def _get_query_variants(self, question: str, entity: str = None) -> List[str]:
        return query_understanding.get_query_variants(self, question, entity)

    def _generate_variants_with_llm(self, question: str, entity: str = None) -> List[str]:
        return query_understanding.generate_variants_with_llm(self, question, entity)

    def _infer_target_type(self, question_lower: str, intent: str) -> str:
        return query_understanding.infer_target_type(question_lower, intent)

    def _llm_cypher_detection(self, question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
        return query_understanding.llm_cypher_detection(self, question_lower, entity, intent)

    def _fallback_pattern_detection(self, question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
        return query_understanding.fallback_pattern_detection(question_lower, entity, intent)

    def _handle_aggregation_query(self, query_info: Dict[str, Any]) -> Optional[str]:
        """Try to answer aggregation queries directly via Neo4j property graph."""
        agg = query_info.get('aggregation')
        if not agg:
            return None

        # Handle new LLM-generated Cypher queries
        if agg.get('type') == 'cypher':
            cypher_query = agg.get('cypher_query', '')
            if cypher_query:
                return self._execute_cypher_query(cypher_query)
            return None

        # Handle old pattern-based aggregation
        if agg.get('type') != 'aggregation':
            return None

        dynasty_name = query_info.get('entity', '')
        if not dynasty_name:
            return None

        if agg.get('scope') == 'Dynasty' and agg.get('target') == 'Person':
            answer = self._query_dynasty_reign_aggregation(dynasty_name, agg)
            if answer:
                return answer
        
        # Handle emperor position queries: "vua thứ mấy"
        if agg.get('type') == 'emperor_position':
            position = agg.get('position', 0)
            dynasty_name = agg.get('dynasty', '')
            person_name = agg.get('person', '')
            return self._find_emperor_position(person_name, dynasty_name)

        return None

    def _handle_temporal_query(self, query_info: Dict[str, Any]) -> Optional[str]:
        """Direct Cypher lookup for birth/death/burial properties."""
        entity = query_info.get('entity', '')
        intent = query_info.get('intent', '')
        if not entity:
            return None

        cypher = """
        MATCH (p:Person)
        WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS toLower($entity)
           OR toLower(coalesce(toStringOrNull(p.full_name), "")) CONTAINS toLower($entity)
           OR toLower(coalesce(toStringOrNull(p.real_name), "")) CONTAINS toLower($entity)
           OR toLower(coalesce(toStringOrNull(p.birth_name), "")) CONTAINS toLower($entity)
        RETURN p.name as name,
               p.birth_year as birth_year, p.birth_date as birth_date,
               p.death_year as death_year, p.death_date as death_date,
               p.burial_date as burial_date
        LIMIT 3
        """
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                records = list(session.run(cypher, entity=entity))
                for r in records:
                    name = r.get('name', '')
                    by = r.get('birth_year')
                    bd = r.get('birth_date')
                    dy = r.get('death_year')
                    dd = r.get('death_date')
                    burid = r.get('burial_date')

                    info = []
                    if intent in ['birth_year', 'birth_date'] and (by or bd):
                        # Birth-related questions: prefer full birth_date output only.
                        # If birth_date is missing, fallback to birth_year.
                        if bd:
                            info.append(f"sinh ngày {bd}")
                        elif by:
                            info.append(f"sinh năm {by}")
                    elif intent in ['death_year', 'death_date'] and (dy or dd):
                        if dy:
                            info.append(f"mất năm {dy}")
                        if dd:
                            info.append(f"mất ngày {dd}")
                    elif intent == 'burial_date' and burid:
                        info.append(f"an táng: {burid}")

                    if info:
                        return f"{name}: {'; '.join(info)}"
        except Exception as e:
            print(f"[Temporal Query] Error: {e}")
        return None

    def _handle_notable_works_query(self, query_info: Dict[str, Any]) -> Optional[str]:
        """Direct lookup for notable works to stabilize equivalent phrasings."""
        entity = query_info.get("entity", "")
        if not entity:
            return None

        cypher = """
        MATCH (p:Person)
        WHERE toLower(coalesce(toStringOrNull(p.name), "")) CONTAINS toLower($entity)
           OR toLower(coalesce(toStringOrNull(p.full_name), "")) CONTAINS toLower($entity)
           OR toLower(coalesce(toStringOrNull(p.other_name), "")) CONTAINS toLower($entity)
        RETURN p.name as name,
               p.notable_works as notable_works,
               p.works as works
        LIMIT 3
        """
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                records = list(session.run(cypher, entity=entity))
                for r in records:
                    name = r.get("name") or entity
                    work_values: List[str] = []
                    for key in ["notable_works", "works"]:
                        value = r.get(key)
                        if isinstance(value, list):
                            work_values.extend([str(v).strip() for v in value if str(v).strip()])
                        elif value:
                            raw = str(value).strip()
                            if raw:
                                parts = [p.strip(" .;-") for p in re.split(r"[;\n•\\-]+", raw) if p.strip(" .;-")]
                                work_values.extend(parts if parts else [raw])

                    deduped = []
                    seen = set()
                    for item in work_values:
                        k = item.lower()
                        if k not in seen:
                            seen.add(k)
                            deduped.append(item)

                    if deduped:
                        return f"Các tác phẩm tiêu biểu của {name} gồm: {', '.join(deduped[:8])}."
        except Exception as e:
            print(f"[Notable Works Query] Error: {e}")
        return None

    def _is_compound_question(self, question: str) -> bool:
        return query_understanding.is_compound_question(question)

    def _should_use_direct_notable_works(self, question: str) -> bool:
        return query_understanding.should_use_direct_notable_works(question)

    def _is_birth_and_location_question(self, question: str) -> bool:
        return query_understanding.is_birth_and_location_question(question)

    def _handle_birth_and_location_query(self, query_info: Dict[str, Any]) -> Optional[str]:
        return query_handlers.handle_birth_and_location_query(self, query_info)

    def _execute_cypher_query(self, cypher_query: str) -> Optional[str]:
        """Execute a Cypher query and format the result as a natural language answer."""
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                result = session.run(cypher_query)
                records = list(result)
                
                if not records:
                    return "Không tìm thấy thông tin phù hợp."
                
                # For now, assume single result queries like min/max
                if len(records) == 1:
                    record = records[0]
                    # Generic formatting - just return the values
                    values = [str(record[key]) for key in record.keys()]
                    return " ".join(values)
                else:
                    # For multiple results, summarize
                    return f"Tìm thấy {len(records)} kết quả."
                    
        except Exception as e:
            print(f"[ERROR] Cypher query execution failed: {e}")
            return f"Lỗi thực thi truy vấn: {e}"

    def _query_dynasty_reign_aggregation(self, dynasty_name: str, agg: Dict[str, Any]) -> Optional[str]:
        """Run direct Cypher for dynasty-level reign aggregation."""
        order = 'ASC' if agg['operation'] == 'min' else 'DESC'
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            # Prefer exact reign duration properties first
            duration_result = session.run(
                """
                MATCH (p:Person)-[:BELONGS_TO_DYNASTY]->(d:Dynasty)
                WHERE toLower(d.name) CONTAINS toLower($dynasty)
                WITH p, d,
                     coalesce(
                         toInteger(p.reign_duration_days),
                         toInteger(p.reign_length_days),
                         toInteger(p.duration_days),
                         toInteger(p.thoi_gian_tri_vi_ngay)
                     ) AS duration
                WHERE duration IS NOT NULL
                RETURN p.name AS person_name, d.name AS dynasty, duration
                ORDER BY duration %s
                LIMIT 1
                """ % order,
                dynasty=dynasty_name
            )

            record = duration_result.single()
            if record:
                person_name = record['person_name']
                dynasty = record['dynasty']
                duration = record['duration']
                unit = 'ngày'
                suffix = 'ngắn nhất' if agg['operation'] == 'min' else 'lâu nhất'
                return f"Vua {person_name} là vua {suffix} trong triều {dynasty} với {duration} {unit}."

            # Fallback: year-based reign interval
            year_result = session.run(
                """
                MATCH (p:Person)-[:BELONGS_TO_DYNASTY]->(d:Dynasty)
                WHERE toLower(d.name) CONTAINS toLower($dynasty)
                WITH p, d,
                     CASE
                         WHEN p.reign_start_year IS NOT NULL AND p.reign_end_year IS NOT NULL
                         THEN abs(toInteger(p.reign_end_year) - toInteger(p.reign_start_year))
                         ELSE NULL
                     END AS duration_years,
                     toInteger(p.reign_start_year) AS start_year,
                     toInteger(p.reign_end_year) AS end_year
                WHERE duration_years IS NOT NULL
                RETURN p.name AS person_name, d.name AS dynasty, duration_years, start_year, end_year
                ORDER BY duration_years %s
                LIMIT 1
                """ % order,
                dynasty=dynasty_name
            )

            record = year_result.single()
            if record:
                person_name = record['person_name']
                dynasty = record['dynasty']
                duration_years = record['duration_years']
                suffix = 'ngắn nhất' if agg['operation'] == 'min' else 'lâu nhất'
                return f"Vua {person_name} là vua {suffix} trong triều {dynasty} với khoảng {duration_years} năm trị vì."

        return None

    def _find_emperor_position(self, person_name: str, dynasty_name: str) -> Optional[str]:
        """Find the emperor's position (thứ mấy) in a dynasty by reign_start_year."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            # First, get the person's reign_start_year
            person_result = session.run(
                """
                MATCH (p:Person)
                WHERE toLower(p.name) CONTAINS toLower($person)
                RETURN p.name as name, toInteger(p.reign_start_year) as start_year
                LIMIT 1
                """,
                person=person_name
            )
            
            person_record = person_result.single()
            if not person_record:
                return None
            
            start_year = person_record['start_year']
            actual_name = person_record['name']
            
            if not start_year:
                return None
            
            # Find all emperors in the dynasty ordered by reign_start_year
            dynasty_result = session.run(
                """
                MATCH (p:Person)-[:BELONGS_TO_DYNASTY]->(d:Dynasty)
                WHERE toLower(d.name) CONTAINS toLower($dynasty)
                AND p.reign_start_year IS NOT NULL
                WITH p, d, toInteger(p.reign_start_year) as start_y
                ORDER BY start_y ASC
                RETURN p.name as name, start_y as start_year
                """,
                dynasty=dynasty_name
            )
            
            emperors = list(dynasty_result)
            if not emperors:
                return None
            
            # Find position (1-indexed)
            for idx, emp in enumerate(emperors, 1):
                if emp['start_year'] == start_year:
                    return f"{actual_name} là vua thứ {self._number_to_vietnamese(idx)} của nhà {dynasty_name.replace('triều ', '').replace('nhà ', '')}."
            
            return None

    def _number_to_vietnamese(self, num: int) -> str:
        """Convert number to Vietnamese ordinal (1 -> một, 2 -> hai, etc.)."""
        vietnamese_numbers = {
            1: "nhất", 2: "hai", 3: "ba", 4: "tư", 5: "năm",
            6: "sáu", 7: "bảy", 8: "tám", 9: "chín", 10: "mười"
        }
        return vietnamese_numbers.get(num, str(num))

    # =========================================================================
    # 2. CANDIDATE RETRIEVAL (DB-driven 100%)
    # =========================================================================

    def _retrieve_candidates(self, query_info: Dict) -> List[Dict]:
        return query_retrieval.retrieve_candidates(self, query_info, SEMANTIC_AVAILABLE)

    def _search_events(self, entity: str, keywords: List[str], event_type: str = None, temporal_emperor: str = None) -> List[Dict]:
        return query_search.search_events(self, entity, keywords, event_type, temporal_emperor)

    def _extract_emperor_from_query(self, keywords: List[str]) -> str:
        return query_search.extract_emperor_from_query(keywords)

    def _get_emperor_reign_dates(self, session, emperor_name: str) -> dict:
        return query_search.get_emperor_reign_dates(self, session, emperor_name)

    def _event_during_reign(self, event_date: str, emperor_reign: dict) -> bool:
        return query_search.event_during_reign(event_date, emperor_reign)

    def _search_people_with_titles(self) -> List[Dict]:
        return query_search.search_people_with_titles(self)

    def _search_by_name_alias(self, entity: str, keywords: List[str]) -> List[Dict]:
        return query_search.search_by_name_alias(self, entity, keywords)

    def _search_name_alias_for_entity(self, entity: str, intent: str) -> List[Dict]:
        return query_search.search_name_alias_for_entity(self, entity, intent)

    def _search_relationship_for_entity(self, entity: str, intent: str) -> List[Dict]:
        return query_search.search_relationship_for_entity(self, entity, intent)

    def _fulltext_search(self, entity: str, keywords: List[str], include_events: bool = False) -> List[Dict]:
        return query_search.fulltext_search(self, entity, keywords, include_events=include_events)

    def _get_all_names_for_node(self, session, node_eid: str) -> List[Dict]:
        return query_search.get_all_names_for_node(session, node_eid)

    def _soft_matching_search(self, entity: str, keywords: List[str]) -> List[Dict]:
        return query_search.soft_matching_search(self, entity, keywords)

    def _vector_search(self, query: str) -> List[Dict]:
        return query_search.vector_search(self, query)

    # =========================================================================
    # 3. GRAPH EXPANSION (DB-driven) - FULL BIDIRECTIONAL EXPANSION
    # =========================================================================

    def _expand_graph(self, candidates: List[Dict]) -> List[Dict]:
        return query_expansion.expand_graph(self, candidates)
    
    def _get_person_context(self, session, person_eid: str) -> Dict:
        return query_expansion.get_person_context(self, session, person_eid)
    
    def _format_relationship(self, rel_type: str, is_outgoing: bool, target_name: str, rel_props = None) -> str:
        """
        Format relationship text theo đúng chiều và thuộc tính.
        
        User's Neo4j convention:
        - (Đồng Khánh)-[CHILD_OF {relationship_type: 'adoptive'}]->(Tự Đức) 
          → Đồng Khánh là CON NUÔI CỦA Tự Đức
        - (Đồng Khánh)-[CHILD_OF {relationship_type: 'biological'}]->(Nguyễn Phúc Hồng Cai)
          → Đồng Khánh là CON RUỘTcủa Nguyễn Phúc Hồng Cai
        
        is_outgoing=True: p-[rel]->target → target là parent của p
        is_outgoing=False: p<-[rel]-target → target là parent của p
        """
        if rel_props is None:
            rel_props = {} if isinstance(rel_props, dict) else {}
        elif not isinstance(rel_props, dict):
            rel_props = {}
        
        # === FIX: Handle CHILD_OF with relationship_type property ===
        if rel_type.upper() == "CHILD_OF":
            rel_subtype = rel_props.get("relationship_type", "")
            
            if rel_subtype.lower() == "adoptive":
                return f"{target_name} (là cha/mẹ NUÔI)"
            elif rel_subtype.lower() == "biological":
                return f"{target_name} (là cha/mẹ RUỘTcủa p)"
            else:
                return f"{target_name} (là cha/mẹ của p)"
        
        if rel_type.upper() == "PARENT_OF":
            if is_outgoing:
                return f"{target_name} (là con của p)"
            else:
                return f"p (là cha/mẹ của {target_name})"
        
        if rel_type.upper() == "FATHER_OF":
            rel_subtype = rel_props.get("relationship_type", "")
            if rel_subtype.lower() == "adoptive":
                return f"{target_name} (là cha NUÔI)"
            elif rel_subtype.lower() == "biological":
                return f"{target_name} (là cha RUỘTcủa p)"
            else:
                if is_outgoing:
                    return f"{target_name} (là con của p)"
                else:
                    return f"p (là cha của {target_name})"
        
        if rel_type.upper() == "MOTHER_OF":
            rel_subtype = rel_props.get("relationship_type", "")
            if rel_subtype.lower() == "adoptive":
                return f"{target_name} (là mẹ NUÔI)"
            elif rel_subtype.lower() == "biological":
                return f"{target_name} (là mẹ RUỘTcủa p)"
            else:
                if is_outgoing:
                    return f"{target_name} (là con của p)"
                else:
                    return f"p (là mẹ của {target_name})"
        
        if rel_type.upper() == "CARED_BY":
            return f"{target_name} (là người nuôi dạy/chăm sóc)"
        
        if rel_type.upper() == "SPOUSE_OF":
            # Show marriage year if available to distinguish current vs ex-spouse
            start_year = rel_props.get("start_year") if rel_props else None
            if start_year:
                return f"{target_name} (là vợ/chồng, năm {start_year})"
            else:
                return f"{target_name} (là vợ/chồng cũ)"
        
        if rel_type.upper() == "SIBLING_OF":
            rel_subtype = rel_props.get("relationship_type", "")
            if rel_subtype.lower() == "half_sibling":
                return f"{target_name} (là anh chị em cùng cha/mẹ)"
            elif rel_subtype.lower() == "full_sibling":
                return f"{target_name} (là anh chị em ruột)"
            else:
                return f"{target_name} (là anh chị em của p)"
        
        if rel_type.upper() == "SUCCESSOR_OF":
            rel_type_prop = rel_props.get("type", "")
            certainty_text = f" ({rel_type_prop})" if rel_type_prop else ""
            if is_outgoing:
                return f"{target_name} (là người kế nhiệm của p){certainty_text}"
            else:
                return f"p (là người kế nhiệm của {target_name}){certainty_text}"
        
        if rel_type.upper() == "PREDECESSOR_OF":
            rel_type_prop = rel_props.get("type", "")
            certainty_text = f" ({rel_type_prop})" if rel_type_prop else ""
            if is_outgoing:
                return f"{target_name} (là người tiền nhiệm của p){certainty_text}"
            else:
                return f"p (là người tiền nhiệm của {target_name}){certainty_text}"
        
        return f"{target_name} ({rel_type})"

    # =========================================================================
    # 4. CONTEXT FILTERING (LLM - CHỈ filter, KHÔNG search)
    # =========================================================================

    def _filter_context(self, query_info: Dict, candidates: List[Dict]) -> str:
        return query_formatting.filter_context(self, query_info, candidates)

    def _format_candidates(self, candidates: List[Dict], main_entity_name: str = None) -> str:
        return query_formatting.format_candidates(candidates, main_entity_name=main_entity_name)

    # =========================================================================
    # 5. ANSWER GENERATION (LLM)
    # =========================================================================

    def _generate_answer(self, query_info: Dict, context: str) -> str:
        return query_handlers.generate_answer(self, query_info, context)

    def _no_data_answer(self, query_info: Dict) -> str:
        return query_handlers.no_data_answer()

    # =========================================================================
    # MAIN PIPELINE
    # =========================================================================

    def process_query(self, question: str) -> str:
        """
        Main pipeline - theo đúng kiến trúc DB-driven + LLM filter.
        
        Flow:
        1. Query Understanding (Rule-based)
        2. Candidate Retrieval (DB)
        3. Graph Expansion (DB)
        4. Context Filtering (LLM)
        5. Answer Generation (LLM)
        """
        print(f"\n{'='*60}")
        print(f"📝 Query: {question}")
        print(f"{'='*60}")

        # ===== 1. QUERY UNDERSTANDING =====
        print("\n[1/5] Query Understanding...")
        query_info = self._understand_query(question)
        print(f"  Entity: {query_info['entity']}")
        print(f"  Intent: {query_info['intent']}")
        print(f"  Keywords: {query_info['keywords']}")
        if query_info.get('aggregation'):
            print(f"  ⚡ Aggregation query detected: {query_info['aggregation']}")
            agg_answer = self._handle_aggregation_query(query_info)
            if agg_answer:
                print("  ✅ Aggregation query answered by graph property search")
                return agg_answer
            print("  ⚠️ Aggregation query fallback to normal pipeline")

        original_q = query_info.get("original_question", "")
        is_compound = self._is_compound_question(original_q)
        is_birth_location = self._is_birth_and_location_question(original_q)

        if is_birth_location:
            birth_location_answer = self._handle_birth_and_location_query(query_info)
            if birth_location_answer:
                print("  ✅ Compound birth+location answered directly from DB")
                return birth_location_answer
            print("  ⚠️ Compound birth+location fallback to normal pipeline")

        if query_info.get('intent') in ['birth_year', 'death_year', 'birth_date', 'death_date', 'burial_date']:
            if not is_compound:
                temporal_answer = self._handle_temporal_query(query_info)
                if temporal_answer:
                    print("  ✅ Temporal query answered directly from DB")
                    return temporal_answer
                print("  ⚠️ Temporal query fallback to normal pipeline")
            else:
                print("  [Temporal] Compound question detected, skip direct temporal answer")

        if query_info.get('intent') == 'notable_works':
            if self._should_use_direct_notable_works(original_q):
                works_answer = self._handle_notable_works_query(query_info)
                if works_answer:
                    print("  ✅ Notable works answered directly from DB")
                    return works_answer
                print("  ⚠️ Notable works fallback to normal pipeline")
            else:
                print("  [Notable Works] Contextual question detected, use full pipeline for richer answer")

        if not query_info.get("entity"):
            print("  ⚠️ Không trích xuất được entity")
            return self._no_data_answer(query_info)

        # ===== 2. CANDIDATE RETRIEVAL =====
        print("\n[2/5] Candidate Retrieval (DB)...")
        candidates = self._retrieve_candidates(query_info)
        print(f"  Found {len(candidates)} candidates")
        for c in candidates[:3]:
            print(f"    - [{c['type']}] {c['name']} (score: {c.get('score', 0):.2f}, {c.get('source', '?')})")

        if not candidates:
            print("  ⚠️ Không tìm được candidates")
            return self._no_data_answer(query_info)

        # ===== 3. GRAPH EXPANSION =====
        print("\n[3/5] Graph Expansion (DB)...")
        expanded = self._expand_graph(candidates)
        print(f"  Expanded to {len(expanded)} nodes")

        # ===== 4. CONTEXT FILTERING =====
        print("\n[4/5] Context Filtering (LLM)...")
        # Send ALL candidates for verification/debugging of search results
        filtered_context = self._filter_context(query_info, expanded)
        
        if not filtered_context:
            print("  ⚠️ LLM không tìm thấy context phù hợp")
            return self._no_data_answer(query_info)
        
        print(f"  Context length: {len(filtered_context)} chars")
        
        # DEBUG: Print context for successor/predecessor queries
        if query_info.get('intent') in ['SUCCESSOR_OF', 'PREDECESSOR_OF']:
            print(f"  [DEBUG] Context preview for {query_info.get('intent')}:")
            # Print first 2000 chars
            print(filtered_context[:2000])
            print("  [...truncated...]")

        # ===== 5. ANSWER GENERATION =====
        print("\n[5/5] Answer Generation (LLM)...")
        print("  🔗 Calling LLM API with streaming...")
        answer = self._generate_answer(query_info, filtered_context)
        
        print(f"\n{'='*60}")
        print(f"✅ Answer generated successfully")
        print(f"{'='*60}\n")
        
        # LLM now appends active person automatically, so just return the answer
        print(f"Answer:\n{answer}\n")
        return answer

    # =========================================================================
    # LEGACY METHODS (kept for compatibility)
    # =========================================================================

    def _get_semantic_model(self):
        """Lazy load semantic model."""
        if not SEMANTIC_AVAILABLE:
            return None

        if self._semantic_model is None:
            try:
                self._semantic_model = SentenceTransformer(self._semantic_model_name)
                print(f"✅ Loaded semantic model: {self._semantic_model_name}")
            except Exception as e:
                print(f"❌ Không load được semantic model: {e}")
                return None
        return self._semantic_model

    # Legacy alias for backward compatibility
    ask_agent = process_query


# =============================================================================
# STANDALONE FUNCTION (for external callers)
# =============================================================================

def ask_agent(question: str) -> dict:
    """Standalone function for API/Chat - returns dict with answer and active_person."""
    pipeline = QueryPipeline()
    result = pipeline.process_query(question)
    
    # Extract answer and active_person if appended
    if "\n\nActive person:" in result:
        parts = result.split("\n\nActive person:")
        answer = parts[0].strip()
        active_person = parts[1].strip() if len(parts) > 1 else None
        return {"answer": answer, "active_person": active_person}
    else:
        return {"answer": result, "active_person": None}
