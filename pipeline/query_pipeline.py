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
from typing import Dict, Any, Optional, List, Tuple
from graph.storage import GraphDB
from llm.answer_generator import AnswerGenerator
from llm.llm_client import call_llm

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
        """
        Phân tích câu hỏi - rule-based nhẹ, LLM chỉ là fallback.
        
        Returns:
            {
                "entity": "tên người/sự kiện",
                "intent": "identity | birth_name | ACHIEVED | ...",
                "target_type": "Person | Event | Dynasty | *",
                "keywords": ["các từ khóa"]
            }
        """
        question_lower = question.lower()

        # 1.1 Rule-based extraction - PRIORITIZE DB person names FIRST
        # Try to find known person names from DB first (catches "Lê Long Đĩnh", "Trần Thái Tông", etc.)
        db_names = self._find_person_names_in_question(question)
        if db_names:
            entity = db_names[0]  # Use first (most relevant) name from DB
        else:
            entity = self._extract_entity(question)
        
        keywords = self._extract_keywords(question)

        # 1.2 Intent detection - Ưu tiên keyword DÀI HƠN trước
        intent = "identity"  # default
        # Sắp xếp theo độ dài giảm dần để ưu tiên "sinh năm" > "sinh"
        sorted_mappings = sorted(self.INTENT_MAPPING.items(), key=lambda x: len(x[0]), reverse=True)
        for keyword, mapped_intent in sorted_mappings:
            if keyword in question_lower:
                intent = mapped_intent
                break

        # 1.3 Target type inference (simple rule)
        target_type = self._infer_target_type(question_lower, intent)

        # 1.4 Aggregation / comparison detection
        aggregation = self._llm_cypher_detection(question_lower, entity, intent)

        return {
            "entity": entity,
            "intent": intent,
            "target_type": target_type,
            "keywords": keywords,
            "aggregation": aggregation,
            "original_question": question
        }

    # =========================================================================
    # SYNONYM MANAGEMENT - DB-driven synonyms
    # =========================================================================

    def _load_synonyms_from_db(self) -> Dict[str, List[str]]:
        """
        Load synonyms từ DB.
        DB Structure: (:Word {name: "đăng quang"})-[:SYNONYM]->(:Word {name: "lên ngôi"})
        
        Cache kết quả trong class variable để không query lại nhiều lần.
        
        FIX: Nếu DB không có synonym, dùng fallback groups ngay.
        """
        if self._synonym_cache:
            return self._synonym_cache
        
        if not self.graph_db or not self.graph_db.driver:
            # Fallback về hard-coded groups
            return self._build_synonym_cache_from_groups()
        
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                # Query synonyms từ DB
                result = session.run("""
                    MATCH (w1:Word)-[:SYNONYM]-(w2:Word)
                    RETURN w1.name as word1, w2.name as word2
                """)
                
                synonym_map: Dict[str, set] = {}
                count = 0
                for r in result:
                    w1 = r.get("word1", "")
                    w2 = r.get("word2", "")
                    if w1 and w2:
                        count += 1
                        if w1 not in synonym_map:
                            synonym_map[w1] = set()
                        if w2 not in synonym_map:
                            synonym_map[w2] = set()
                        synonym_map[w1].add(w2)
                        synonym_map[w2].add(w1)
                
                # Convert set to list
                for word, synonyms in synonym_map.items():
                    self._synonym_cache[word] = list(synonyms)
                
                print(f"  [Synonyms] Loaded {count} synonym pairs from DB")
                
                # FIX: Nếu DB không có synonym (count = 0), dùng fallback
                if count == 0:
                    print(f"  [Synonyms] DB has no synonyms, using fallback groups")
                    return self._build_synonym_cache_from_groups()
                
                return self._synonym_cache
                
        except Exception as e:
            # FIX: Bắt exception do label/relationship không tồn tại và dùng fallback
            print(f"  [Synonyms] DB load failed: {e}, using fallback")
            return self._build_synonym_cache_from_groups()

    def _build_synonym_cache_from_groups(self) -> Dict[str, List[str]]:
        """Build synonym cache từ hard-coded groups."""
        for group in EVENT_SYNONYM_GROUPS:
            for word in group:
                if word not in self._synonym_cache:
                    self._synonym_cache[word] = []
                # Add all other words in group as synonyms
                for other in group:
                    if other != word and other not in self._synonym_cache[word]:
                        self._synonym_cache[word].append(other)
        print(f"  [Synonyms] Built {len(self._synonym_cache)} synonyms from groups")
        return self._synonym_cache

    def _get_synonyms(self, word: str) -> List[str]:
        """Get synonyms cho một từ."""
        if not self._synonym_cache:
            self._load_synonyms_from_db()
        return self._synonym_cache.get(word, [])

    def _expand_query_with_synonyms(self, keywords: List[str]) -> List[str]:
        """
        Expand keywords với synonyms.
        VD: ["đăng quang"] → ["đăng quang", "lên ngôi", "đăng cơ", ...]
        """
        expanded = list(keywords)  # Keep original
        
        for kw in keywords:
            synonyms = self._get_synonyms(kw)
            for syn in synonyms:
                if syn not in expanded:
                    expanded.append(syn)
        
        return expanded

    def _extract_entity(self, question: str) -> str:
        """Trích xuất entity từ câu hỏi - XỬ LÝ NHIỀU DẠNG."""
        # === Filter out particles FIRST ===
        question_clean = question
        particles = ['thứ mấy', 'bao lâu', 'bao lâu?', 'mấy năm', 'bao năm', 'bao giờ']
        for particle in particles:
            question_clean = question_clean.replace(particle, '')
        
        # === CÁC PATTERN theo thứ tự ưu tiên ===
        patterns = [
            # 0. NEW: "Sau khi X [verb], ai/gì [main question]?" - extract main question part
            # Match the actual question after temporal clause
            (r'Sau khi\s+.+?(?:,|\s+)\s*(.+?)(?:\s+tự\s+xưng|\s+chiếm|\s+có|\s+được|\s+là|$|\?)', 1),
            # 0.5: NEW: "Lần 1/lần thứ nhất, ai [verb]?" - extract after lần marker
            (r'(?:lần\s+\d+|lần\s+thứ\s+\w+)\s*,?\s*(.+?)(?:\s+chiếm|\s+tự\s+xưng|\s+là|$|\?)', 1),
            # 0. FIX: "Vua/Hoàng đế X Y?" - extract X (person name after title)
            (r'(?:vua|hoàng\s+đế|thái\s+tử|vương|công|tước)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:tại|trị|sinh|mất|là|của|bao)|\?|$)', 1),
            # 0.5. NEW: "việc X bị..." or "việc X được..." - catch mid-sentence person events
            (r'việc\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:bị|được|lên|đổi|phế|thoái|qua|tịch))', 1),
            # 0.7. NEW: "Sau khi/Khi X [verb]..." - temporal phrase with person
            (r'(?:Sau khi|khi|Khi)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:thoái|đăng|lên|xuống|bị|được))', 1),
            # 1. Relationship queries: "Người kế nhiệm/tiền nhiệm X là ai?" - ƯU TIÊN TRƯỚC
            (r'người\s+(kế\s+nhiệm|tiền\s+nhiệm)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+ai)', 2),
            # 2. "X là Y phải không?" - "Bảo Đại là vua cuối cùng của triều Nguyễn phải không?"
            (r'^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+.+?phải\s+không)', 1),
            # 3. "X là ai/gì/ở đâu" - "Bảo Đại là ai?"
            (r'^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+ai|\s+là\s+gì|\s+ở\s+đâu)', 1),
            # 3.5. NEW: "X được [verb]..." - handle "X được mệnh danh gì"
            (r'\b([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])\s+(?:được|là|gọi|mệnh|đoạt)', 1),
            # 4. "X?" - standalone name at start
            (r'^([A-ZÀ-ỹ][a-zà-ỹ]{2,})(?:\s+|$|\?)', 1),
            # 5. "tên/của X?" - "tên thật của Bảo Đại?"
            (r'(?:tên|của|ai là|gì là)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\?|$)', 1),
            # 6. "Sau khi [event], X [verb]" - "Sau khi thoái vị, Bảo Đại giữ..."
            (r',?\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có|ở|sống|mất|năm|nơi|được\s+tổ))', 1),
            # 7. "trong/cho/với X" - "trong Chính phủ VNDCCH"
            (r'(?:trong|cho|với)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s|$|\?)', 1),
            # 8. "năm 1945, X" - "năm 1945, Bảo Đại"
            (r',\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có))', 1),
        ]

        for pattern, group in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                extracted = match.group(group).strip()
                # Loại bỏ temporal suffixes
                temporal_suffixes = ["sinh năm", "mất năm", "đăng quang", "lên ngôi", "thoái vị", "năm nào", "lúc nào", "ra sao", "tự xưng", "tự xưng là", "tử nạn", "bị phế truất"]
                for suffix in temporal_suffixes:
                    if extracted.lower().endswith(suffix):
                        extracted = extracted[:-len(suffix)].strip()
                    # Also check pattern with space before suffix
                    if " " + suffix in " " + extracted.lower():
                        extracted = extracted[:extracted.lower().rfind(" " + suffix)].strip()
                # Loại bỏ từ không phải tên
                stopwords = {"ai", "gì", "ở", "đâu", "nào", "chính", "phủ", "việt", "nam", "dân", "chủ", "cộng", "hòa", "vai", "trò", "sau", "khi", "trong", "cho", "với", "năm", "tháng", "ngày", "lời", "bài", "vua", "hoàng", "đế", "thái", "tử", "vương", "công", "tước", "được", "là", "tự", "xưng", "hiệu"}
                words = extracted.split()
                cleaned = " ".join(w for w in words if w.lower() not in stopwords)
                if cleaned and len(cleaned) > 2:
                    return cleaned

        # === NEW FALLBACK 1: Search database for any known person name in question ===
        # This catches cases like "việc Dục Đức bị phế truất" where patterns may not work
        try:
            all_names = self._find_person_names_in_question(question)
            if all_names:
                return all_names[0]  # Return best match
        except Exception as e:
            pass  # Fall through to next fallback

        # === Fallback 2: Word segmentation lấy tên riêng ===
        if WORD_SEG_AVAILABLE:
            words = underthesea.word_tokenize(question)
            entity_words = []
            stopwords = {"sinh", "mất", "năm", "lên", "đăng", "ngày", "tháng", "lúc", "thôi", "là", "ai", "gì", "ở", "đâu", "của", "sau", "khi", "trong", "vai", "trò", "giữ", "được", "chính", "phủ", "việt", "nam", "dân", "chủ", "cộng", "hòa", "?", "vua", "hoàng", "đế", "thái", "tử"}
            for w in words:
                if w.lower() in stopwords:
                    continue
                if w[0].isupper() if w else False:
                    entity_words.append(w)
            if entity_words:
                return " ".join(entity_words[:2])  # Lấy 1-2 từ đầu

        # === Fallback 3: lấy từ hoa đầu tiên ===
        words = question.split()
        for w in words:
            if w[0].isupper() if w else False:
                return w

        return question.strip().rstrip("?").strip()

    def _find_person_names_in_question(self, question: str) -> List[str]:
        """
        NEW: Search database for any known person names mentioned in the question.
        This helps catch cases like "việc Dục Đức bị phế truất" where Dục Đức is mid-sentence.
        Also handles partial names like "Chiêu Hoàng" → "Lý Chiêu Hoàng"
        Returns list of person names found, ordered by relevance.
        """
        if not self.graph_db or not self.graph_db.driver:
            return []
        
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                # Query all person names from database
                result = session.run("""
                    MATCH (p:Person)
                    RETURN p.name as name, p.full_name as full_name, p.other_name as other_name
                    LIMIT 500
                """)
                
                found_names = []
                question_lower = question.lower()
                record_count = 0
                
                for record in result:
                    record_count += 1
                    name = (record.get("name") or "").strip()
                    full_name = (record.get("full_name") or "").strip()
                    other_name = (record.get("other_name") or "").strip()
                    
                    # Check if any name appears in question (exact match or as suffix)
                    found_match = False
                    match_specificity = 0  # Track how specific the match is
                    
                    for candidate_name in [name, full_name, other_name]:
                        if not candidate_name or len(candidate_name) <= 2:
                            continue
                            
                        candidate_lower = candidate_name.lower()
                        
                        # Try exact match first (e.g., "lý chiêu hoàng" in question)
                        if candidate_lower in question_lower:
                            found_names.append((candidate_name, 1000 + len(candidate_lower.split())))  # Exact match = highest priority
                            found_match = True
                            break
                        
                        # Try suffix match for compound names (e.g., "chiêu hoàng" matches "lý chiêu hoàng")
                        # Split by spaces and check if last N words appear in question
                        name_words = candidate_lower.split()
                        for i in range(1, len(name_words)):
                            suffix = " ".join(name_words[i:])  # "chiêu hoàng", "hoàng", etc.
                            if len(suffix) > 2 and suffix in question_lower:
                                # Score = number of words in suffix (longer suffix = more specific)
                                specificity = len(suffix.split())
                                found_names.append((candidate_name, specificity))
                                found_match = True
                                break
                        if found_match:
                            break
                
                # Sort by specificity DESC (higher = more specific), then by length DESC
                found_names.sort(key=lambda x: (x[1], len(x[0])), reverse=True)
                result_names = [name for name, _ in found_names]
                
                # Return names ordered by specificity (not just length!)
                return result_names
        except Exception as e:
            print(f"  [ERROR] _find_person_names_in_question failed: {str(e)[:100]}")
            return []

    def _extract_keywords(self, question: str) -> List[str]:
        """
        Trích xuất keywords từ câu hỏi - GIỮ "tên" vì keyword QUAN TRỌNG.
        VD: "tên khai sinh của Bảo Đại" → ["tên", "khai", "sinh", "bảo", "đại"]
        """
        # Stopwords NHẸ - KHÔNG loại "tên" vì quan trọng cho search
        stopwords = {
            'là', 'ai', 'gì', 'đâu', 'khi', 'nào', 'ông', 'bà',
            'của', 'trong', 'với', 'vì', 'cho', 'hay', 'có', 'không', 'và', 'hoặc',
            'được', 'để', 'ra', 'vào', 'lên', 'xuống', 'ở', 'bởi',
            'thứ', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín', 'mười',
            'cho', 'nào', 'những', 'các', 'với'
        }

        if WORD_SEG_AVAILABLE:
            words = underthesea.word_tokenize(question.lower())
        else:
            words = re.findall(r'\b[\wÀ-ỹ]+\b', question.lower())

        return [w for w in words if w not in stopwords and len(w) > 1]

    def _get_query_variants(self, question: str, entity: str = None) -> List[str]:
        """
        Tạo các biến thể của câu hỏi để search hiệu quả hơn.
        
        FIX: Thêm LLM để tạo biến thể câu hỏi.
        VD: "Bảo Đại lên ngôi năm nào?" → 
            - "Bảo Đại đăng quang năm nào?"
            - "Ngày tháng năm sinh của Bảo Đại?"
            - "Bảo Đại sinh thời gian nào?"
        """
        variants = [question]
        question_lower = question.lower()
        
        # === FIX: Dùng LLM để tạo biến thể câu hỏi ===
        try:
            llm_variants = self._generate_variants_with_llm(question, entity)
            if llm_variants:
                variants.extend(llm_variants)
                print(f"  [Variants] LLM generated: {len(llm_variants)} variants")
        except Exception as e:
            print(f"  [Variants] LLM generation failed: {e}, using rule-based")
        
        # === Rule-based variants (fallback) ===
        # Tìm các synonym trong câu hỏi và tạo biến thể
        for key, synonyms in self.QUERY_VARIANTS.items():
            if key in question_lower:
                # Thay thế bằng từng synonym
                for syn in synonyms:
                    variant = question_lower.replace(key, syn)
                    if variant != question_lower:
                        variants.append(variant)
                # Cũng thử kết hợp với tên người
                if entity:
                    for syn in synonyms[:2]:  # Chỉ lấy 2 synonym đầu
                        variants.append(f"{entity} {syn}")

        return list(set(variants))[:8]  # Giới hạn 8 variants

    def _generate_variants_with_llm(self, question: str, entity: str = None) -> List[str]:
        """
        Dùng LLM để tạo các biến thể câu hỏi.
        
        VD: "Bảo Đại sinh năm nào?" → 
            ["Bảo Đại sinh thời gian nào?", "Ngày tháng năm sinh của Bảo Đại?", ...]
        """
        entity_part = f" (entity: {entity})" if entity else ""
        
        prompt = f"""Bạn là chuyên gia tạo biến thể câu hỏi tiếng Việt.
Tạo 3-5 biến thể KHÁC NHAU của câu hỏi sau, giữ nguyên ý nghĩa nhưng dùng từ ngữ khác.{entity_part}

Câu hỏi gốc: "{question}"

YÊU CẦU:
- Mỗi biến thể phải KHÁC với câu gốc và với nhau
- Dùng từ đồng nghĩa, cách diễn đạt khác
- Giữ nguyên entity (tên người/sự kiện)
- Không thay đổi ý nghĩa câu hỏi

Trả về MỖI câu hỏi trên 1 dòng, không đánh số, không có giải thích."""

        try:
            response = call_llm(prompt, model=self.model, temperature=0.8)
            
            # Parse response - mỗi dòng là 1 variant
            lines = [line.strip() for line in response.strip().split('\n') if line.strip()]
            
            # Filter ra những variant hợp lệ (khác với câu gốc)
            variants = [v for v in lines if v and v.lower() != question.lower()][:5]
            
            return variants
        except Exception as e:
            print(f"  [Variants] LLM call failed: {e}")
            return []

    def _infer_target_type(self, question_lower: str, intent: str) -> str:
        """Infer target node type từ câu hỏi."""
        if any(w in question_lower for w in ['triều', 'đại']):
            return "Dynasty"
        if any(w in question_lower for w in ['sự kiện', 'chiến tranh', 'trận']):
            return "Event"
        if any(w in question_lower for w in ['vua', 'hoàng đế', 'nhà', 'thái tử']):
            return "Person"
        return "Person"  # default

    def _llm_cypher_detection(self, question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
        """Use LLM to detect if query needs Cypher and generate Cypher if needed."""
        # FIX: Skip LLM Cypher detection for questions with specific entities
        # Only use for logic questions like "vua nào trị vì ngắn nhất?"
        if entity and len(entity.split()) >= 2 and not any(word in entity.lower() for word in ['triều', 'nhà', 'đại']):
            print(f"  [Cypher] Skipping LLM detection for specific entity: {entity}")
            return None
        
        from prompts import CYPHER_DETECTION_PROMPT
        
        prompt = CYPHER_DETECTION_PROMPT.format(question=question_lower)
        
        try:
            default_temp = float(os.getenv('LLM_TEMPERATURE', '0.1'))
            response = call_llm(prompt, model="gemini-2.5-flash-lite", temperature=default_temp)
            # Parse JSON response
            import json
            result = json.loads(response.strip())
            
            if result.get('needs_cypher', False):
                cypher_query = result.get('cypher_query', '')
                if cypher_query:
                    return {
                        'type': 'cypher',
                        'cypher_query': cypher_query,
                        'explanation': result.get('explanation', '')
                    }
        except Exception as e:
            print(f"[WARNING] LLM Cypher detection failed: {e}")
            # Fallback to old pattern-based detection
            return self._fallback_pattern_detection(question_lower, entity, intent)
        
        return None

    def _fallback_pattern_detection(self, question_lower: str, entity: str, intent: str) -> Optional[Dict[str, Any]]:
        """Fallback pattern-based detection when LLM fails."""
        if 'vua' not in question_lower and 'hoàng đế' not in question_lower:
            return None

        # Patterns for minimum/maximum reign duration
        min_duration_patterns = [
            'trị vì ngắn nhất', 'cai trị ngắn nhất', 'trị vì ít nhất',
            'cai trị ít nhất', 'thời gian trị vì ít nhất', 'thời gian cai trị ít nhất',
            'thời gian trị vì ngắn nhất', 'thời gian cai trị ngắn nhất', 'thống trị ngắn nhất'
        ]
        max_duration_patterns = [
            'trị vì lâu nhất', 'cai trị lâu nhất', 'thời gian trị vì lâu nhất',
            'thời gian cai trị lâu nhất', 'thống trị lâu nhất', 'thời gian cai trị dài nhất'
        ]
        first_patterns = ['vua đầu tiên', 'ai là vua đầu tiên', 'vua đầu tiên của', 'vua đầu tiên trong', 'vua đầu tiên ở']
        last_patterns = ['vua cuối cùng', 'ai là vua cuối cùng', 'vua cuối cùng của', 'vua cuối cùng trong', 'vua cuối cùng ở']

        if any(p in question_lower for p in min_duration_patterns):
            return {
                'type': 'aggregation',
                'operation': 'min',
                'metric': 'reign_duration',
                'scope': 'Dynasty',
                'target': 'Person'
            }

        if any(p in question_lower for p in max_duration_patterns):
            return {
                'type': 'aggregation',
                'operation': 'max',
                'metric': 'reign_duration',
                'scope': 'Dynasty',
                'target': 'Person'
            }

        if any(p in question_lower for p in first_patterns):
            return {
                'type': 'aggregation',
                'operation': 'min',
                'metric': 'reign_start_year',
                'scope': 'Dynasty',
                'target': 'Person'
            }

        if any(p in question_lower for p in last_patterns):
            # FIX: Nếu có entity cụ thể (Person name), đây KHÔNG PHẢI aggregation query
            # VD: "Bảo Đại là vua cuối cùng của triều Nguyễn phải không?" - hỏi về Bảo Đại cụ thể
            # KHÔNG phải "Ai là vua cuối cùng của triều Nguyễn?"
            if entity and len(entity.split()) >= 2 and not any(word in entity.lower() for word in ['triều', 'nhà']):
                return None  # Đây là câu hỏi về person cụ thể, không phải aggregation
            return {
                'type': 'aggregation',
                'operation': 'max',
                'metric': 'reign_end_year',
                'scope': 'Dynasty',
                'target': 'Person'
            }
        
        # NEW: Handle "X là vua thứ mấy của triều Y?" - emperor position
        emperor_position_pattern = r"([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])\s+là\s+vua\s+thứ\s+(\w+)\s+(?:của\s+)?(?:triều|nhà)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]*[A-ZÀ-ỹ])"
        match = re.search(emperor_position_pattern, question_lower)
        if match:
            person_name = match.group(1).strip()
            position_word = match.group(2).strip()
            dynasty_name = match.group(3).strip()
            return {
                'type': 'emperor_position',
                'person': person_name,
                'position_word': position_word,
                'dynasty': dynasty_name
            }

        # Fallback for basic reign queries with comparison words
        if 'ngắn nhất' in question_lower and 'trị vì' in question_lower:
            return {
                'type': 'aggregation',
                'operation': 'min',
                'metric': 'reign_duration',
                'scope': 'Dynasty',
                'target': 'Person'
            }

        return None

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
        """
        Tìm kiếm candidates - DB-driven, KHÔNG dùng LLM.
        """
        entity = query_info.get("entity", "")
        keywords = query_info.get("keywords", [])
        intent = query_info.get("intent", "")

        candidates = []
        seen_ids = set()

        # === RELATIONSHIP-BASED SEARCH for all relationship intents ===
        relationship_intents = ["SUCCESSOR_OF", "PREDECESSOR_OF", "ADOPTED_CHILD_OF", "ADOPTIVE_PARENT_OF", 
                               "FOSTER_CHILD_OF", "FOSTER_PARENT_OF"]
        if intent in relationship_intents:
            rel_candidates = self._search_relationship_for_entity(entity, intent)
            print(f"  [Relationship] Found {len(rel_candidates)} relationship candidates for {intent}")
            for c in rel_candidates:
                if c.get("id") not in seen_ids:
                    c["score"] = 2.5
                    candidates.append(c)
                    seen_ids.add(c.get("id"))
                    print(f"    - Added relationship candidate: {c.get('name', 'N/A')} (score: {c.get('score', 0)})")

        # === DEBUG: Check if entity exists in DB ===
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            debug_result = session.run("""
                MATCH (p:Person)
                WHERE toLower(p.name) CONTAINS toLower($entity)
                RETURN p.name as name, p.birth_date as birth_date, p.death_date as death_date
                LIMIT 3
            """, entity=entity)
            debug_persons = list(debug_result)
            if debug_persons:
                print(f"  [DEBUG] DB has Person(s) matching '{entity}':")
                for p in debug_persons:
                    print(f"    - {p['name']} (birth: {p.get('birth_date', 'N/A')}, death: {p.get('death_date', 'N/A')})")
            else:
                print(f"  [DEBUG] NO Person found in DB matching '{entity}'")

        # === SYNONYM EXPANSION ===
        expanded_keywords = self._expand_query_with_synonyms(keywords)
        if expanded_keywords != keywords:
            print(f"  [Synonyms] Expanded: {keywords} → {expanded_keywords}")

        # === NAME-FIRST SEARCH cho "tên thật/birth_name" intent ===
        name_intents = ["birth_name", "real_name", "temple_name", "original_name", "regnal_name"]
        if intent in name_intents:
            name_first_candidates = self._search_name_alias_for_entity(entity, intent)
            for c in name_first_candidates:
                if c.get("id") not in seen_ids:
                    c["score"] = 2.0
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === EVENT SEARCH (NEW) - when intent is event-related ===
        event_intents = ["EVENT", "TREATY", "MILITARY", "REBELLION"]
        if intent in event_intents:
            # Try to find temporal context (emperor name + event search)
            temporal_emperor = self._extract_emperor_from_query(keywords)
            event_candidates = self._search_events(entity, expanded_keywords, intent, temporal_emperor)
            print(f"  [Event] Found {len(event_candidates)} event candidates for intent '{intent}'")
            for c in event_candidates:
                if c.get("id") not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.get("id"))
                    print(f"    - Added event: {c.get('name', 'N/A')} ({c.get('date', 'N/A')})")

        # === NAME-ALIAS SEARCH ===
        name_candidates = self._search_by_name_alias(entity, keywords)
        for c in name_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

        # === FULLTEXT SEARCH (now searches both Person + Event) ===
        ft_candidates = self._fulltext_search(entity, expanded_keywords, include_events=(intent not in event_intents))
        for c in ft_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

        # === FALLBACK: If entity extraction failed (too long/complex), search with keywords instead ===
        if len(candidates) < 5 and len(entity) > 30:
            print(f"  [Fallback] Entity too complex ({len(entity)} chars), searching with keywords instead")
            keyword_candidates = self._fulltext_search("", expanded_keywords, include_events=True)
            for c in keyword_candidates:
                if c.get("id") not in seen_ids:
                    c["score"] = c.get("score", 1.0) * 0.8  # Lower score for fallback
                    candidates.append(c)
                    seen_ids.add(c.get("id"))
            
            # Additional fallback: Search for people with titles (potential emperors/rulers)
            print(f"  [Fallback2] Searching for people with titles...")
            title_search_candidates = self._search_people_with_titles()
            for c in title_search_candidates:
                if c.get("id") not in seen_ids:
                    c["score"] = c.get("score", 1.0) * 0.7
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === SOFT MATCHING (fallback) ===
        if len(candidates) < 3:
            soft_candidates = self._soft_matching_search(entity, expanded_keywords)
            for c in soft_candidates:
                if c.get("id") not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === VECTOR SEARCH (fallback) ===
        if len(candidates) < 3 and SEMANTIC_AVAILABLE:
            vec_candidates = self._vector_search(entity)
            for c in vec_candidates:
                if c.get("id") not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === Sắp xếp theo score và loại bỏ duplicates ===
        def sort_key(c):
            source_priority = {
                "exact_match": 1.0,
                "name_alias:birth_name": 1.0,
                "name_alias": 0.9,
                "fulltext": 0.8,
                "fulltext_fallback": 0.7,
                "soft_match": 0.5,
                "vector": 0.3,
            }
            source = c.get("source", "")
            priority = 0.5
            for key, val in source_priority.items():
                if key in source:
                    priority = val
                    break
            return (1 - priority, -c.get("score", 0))
        
        candidates.sort(key=sort_key)
        
        return candidates[:20]

    def _search_events(self, entity: str, keywords: List[str], event_type: str = None, temporal_emperor: str = None) -> List[Dict]:
        """Search for Event nodes by name, keywords, or event_type.
        
        Args:
            entity: Main entity to search for
            keywords: Keywords to match
            event_type: Type of event (EVENT, TREATY, etc)
            temporal_emperor: Emperor name to filter events by reign dates
        """
        candidates = []
        
        if not self.graph_db or not self.graph_db.driver:
            return candidates
        
        if not entity:
            return candidates
        
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                # First, if we have a temporal emperor, get their reign dates
                emperor_reign = None
                if temporal_emperor:
                    emperor_reign = self._get_emperor_reign_dates(session, temporal_emperor)
                    if emperor_reign:
                        print(f"  [Event] Filtering by emperor reign: {temporal_emperor} ({emperor_reign.get('start')} - {emperor_reign.get('end')})")
                
                # Search by event name or keywords (fulltext on Event nodes)
                event_query = """
                    MATCH (e:Event)
                    WHERE toLower(e.name) CONTAINS toLower($entity)
                       OR toLower(e.description) CONTAINS toLower($entity)
                       OR toLower(e.location) CONTAINS toLower($entity)
                    RETURN elementId(e) as id, e.name as name, e.date as date, 
                           e.event_type as event_type, e.description as description,
                           e.location as location, e.participants as participants,
                           e.significance as significance
                    LIMIT 30
                """
                
                results = session.run(event_query, entity=entity or "")
                
                for record in results:
                    event_id = record.get("id")
                    event_name = record.get("name") or ""
                    event_date = record.get("date") or ""
                    
                    if event_id and event_name:
                        # If we have emperor reign dates, check if event is within that period
                        if emperor_reign:
                            if not self._event_during_reign(event_date, emperor_reign):
                                continue  # Skip events outside the reign period
                        
                        # Calculate relevance score
                        score = 0
                        source = "event_search"
                        
                        entity_lower = entity.lower() if entity else ""
                        if entity_lower and entity_lower in event_name.lower():
                            score = 3.0
                            source = "event_exact_match"
                        elif any(kw and kw.lower() in event_name.lower() for kw in (keywords or [])):
                            score = 2.5
                            source = "event_keyword_match"
                        else:
                            score = 1.5
                            source = "event_fulltext"
                        
                        # Check event_type match (safely handle None)
                        evt_type_str = record.get("event_type") or ""
                        evt_type = evt_type_str.upper() if evt_type_str else ""
                        if event_type and evt_type and event_type.lower() == evt_type.lower():
                            score += 1.0
                        
                        # Boost score if event is within emperor's reign
                        if emperor_reign and self._event_during_reign(event_date, emperor_reign):
                            score += 0.5
                        
                        candidate = {
                            "id": event_id,
                            "type": "Event",
                            "name": event_name,
                            "date": event_date,
                            "event_type": record.get("event_type"),
                            "description": record.get("description", ""),
                            "location": record.get("location", ""),
                            "participants": record.get("participants", ""),
                            "significance": record.get("significance", ""),
                            "score": score,
                            "source": source,
                            "all_names": [],
                            "related": [],
                            "properties": {}
                        }
                        
                        candidates.append(candidate)
                
                # FALLBACK: If no results and event_type is provided, search for all events of that type
                if not candidates and event_type:
                    fallback_query = """
                        MATCH (e:Event)
                        WHERE toLower(e.event_type) = toLower($event_type)
                        RETURN elementId(e) as id, e.name as name, e.date as date,
                               e.event_type as event_type, e.description as description,
                               e.location as location, e.participants as participants,
                               e.significance as significance
                        LIMIT 20
                    """
                    
                    print(f"  [Event] Fallback: searching for all events of type {event_type}")
                    fallback_results = session.run(fallback_query, event_type=event_type)
                    
                    for record in fallback_results:
                        event_id = record.get("id")
                        event_name = record.get("name") or ""
                        event_date = record.get("date") or ""
                        
                        if event_id and event_name:
                            # If we have emperor reign dates, check if event is within that period
                            if emperor_reign:
                                if not self._event_during_reign(event_date, emperor_reign):
                                    continue  # Skip events outside the reign period
                            
                            score = 1.0  # Lower score for fallback results
                            source = "event_type_fallback"
                            
                            candidate = {
                                "id": event_id,
                                "type": "Event",
                                "name": event_name,
                                "date": event_date,
                                "event_type": record.get("event_type"),
                                "description": record.get("description", ""),
                                "location": record.get("location", ""),
                                "participants": record.get("participants", ""),
                                "significance": record.get("significance", ""),
                                "score": score,
                                "source": source,
                                "all_names": [],
                                "related": [],
                                "properties": {}
                            }
                            
                            candidates.append(candidate)
                
                print(f"  [Event Search] Found {len(candidates)} events")
                
                print(f"  [Event Search] Found {len(candidates)} events")
        
        except Exception as e:
            print(f"  [Event Search] Error: {e}")
        
        return candidates

    def _extract_emperor_from_query(self, keywords: List[str]) -> str:
        """Extract emperor name from keywords (e.g., 'Kiến Phúc', 'Dục Đức')."""
        # Common Vietnamese emperor names
        emperor_names = [
            "Kiến Phúc", "Dục Đức", "Đồng Khánh", "Thành Thái", "Khải Định",
            "Bảo Đại", "Cảnh Hùng", "Bình Việt", "Ưng Đăng", "Minh Mạng",
            "Tự Đức", "Tùn Thiện", "Hàm Nghi", "Gia Long", "Minh Huỳền"
        ]
        
        # Check if any emperor name is in keywords
        for keyword in keywords:
            for emperor in emperor_names:
                if emperor.lower() in keyword.lower() or keyword.lower() in emperor.lower():
                    return emperor
        
        return None

    def _get_emperor_reign_dates(self, session, emperor_name: str) -> dict:
        """Get emperor's reign start and end dates."""
        try:
            result = session.run("""
                MATCH (p:Person)
                WHERE toLower(p.name) CONTAINS toLower($emperor)
                   OR toLower(p.main_name) CONTAINS toLower($emperor)
                RETURN p.reign_start as start, p.reign_end as end
                LIMIT 1
            """, emperor=emperor_name)
            
            record = result.single()
            if record:
                return {
                    "start": record.get("start"),
                    "end": record.get("end")
                }
        except Exception as e:
            print(f"  [Event] Error getting reign dates: {e}")
        
        return None

    def _event_during_reign(self, event_date: str, emperor_reign: dict) -> bool:
        """Check if an event date falls within emperor's reign period."""
        if not event_date or not emperor_reign:
            return False
        
        try:
            # Try to extract year from event_date (format: YYYY-MM-DD or YYYY)
            event_year = None
            if isinstance(event_date, str):
                # Try to extract year
                import re
                year_match = re.search(r'(\d{4})', event_date)
                if year_match:
                    event_year = int(year_match.group(1))
            
            if not event_year:
                return False
            
            # Get reign years
            start_year = None
            end_year = None
            
            if emperor_reign.get("start"):
                start_str = str(emperor_reign.get("start"))
                year_match = re.search(r'(\d{4})', start_str)
                if year_match:
                    start_year = int(year_match.group(1))
            
            if emperor_reign.get("end"):
                end_str = str(emperor_reign.get("end"))
                year_match = re.search(r'(\d{4})', end_str)
                if year_match:
                    end_year = int(year_match.group(1))
            
            # Check if event year is within reign period
            if start_year and end_year:
                return start_year <= event_year <= end_year
            elif start_year:
                return event_year >= start_year
            elif end_year:
                return event_year <= end_year
        except Exception as e:
            print(f"  [Event] Error checking event date: {e}")
        
        return False

    def _search_people_with_titles(self) -> List[Dict]:
        """Search for all people with titles (potential emperors/rulers during occupations)."""
        candidates = []
        
        if not self.graph_db or not self.graph_db.driver:
            return candidates
        
        try:
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                # Search for people with titles relating to emperorship
                # Include 16th-17th century occupants: Trần Cảo, Mạc Đăng Dung, etc.
                result = session.run("""
                    MATCH (p:Person)
                    WHERE p.title IS NOT NULL
                      AND (toLower(p.title) CONTAINS 'đế'
                           OR toLower(p.title) CONTAINS 'vua'
                           OR toLower(p.title) CONTAINS 'phó'
                           OR toLower(p.title) CONTAINS 'quốc'
                           OR toLower(p.title) CONTAINS 'công'
                           OR toLower(p.title) CONTAINS 'vương')
                    RETURN elementId(p) as id, p.name as name, p.title as title,
                           p.birth_year as birth_year, p.death_year as death_year,
                           p.description as description
                    LIMIT 30
                """)
                
                for record in result:
                    person_id = record.get("id")
                    person_name = record.get("name") or ""
                    
                    if person_id and person_name:
                        candidate = {
                            "id": person_id,
                            "type": "Person",
                            "name": person_name,
                            "title": record.get("title", ""),
                            "birth_year": record.get("birth_year", ""),
                            "death_year": record.get("death_year", ""),
                            "description": record.get("description", ""),
                            "score": 1.5,
                            "source": "title_search",
                            "all_names": [],
                            "related": [],
                            "properties": {}
                        }
                        candidates.append(candidate)
                
                # Also specifically search for known occupants by name
                print(f"  [Title Search] Found {len(candidates)} people with titles")
                
                # Additional targeted search for specific emperors
                specific_names = ["Trần Cảo", "Mạc Đăng Dung", "Mac Dang Dung"]
                for target_name in specific_names:
                    specific_result = session.run("""
                        MATCH (p:Person)
                        WHERE toLower(p.name) CONTAINS toLower($name)
                        RETURN elementId(p) as id, p.name as name, p.title as title,
                               p.description as description
                        LIMIT 1
                    """, name=target_name)
                    
                    for record in specific_result:
                        person_id = record.get("id")
                        # Check if already in candidates
                        if not any(c.get("id") == person_id for c in candidates):
                            person_name = record.get("name") or ""
                            if person_id and person_name:
                                candidate = {
                                    "id": person_id,
                                    "type": "Person",
                                    "name": person_name,
                                    "title": record.get("title", ""),
                                    "description": record.get("description", ""),
                                    "score": 2.0,  # Higher score for direct match
                                    "source": "specific_search",
                                    "all_names": [],
                                    "related": [],
                                    "properties": {}
                                }
                                candidates.append(candidate)
                                print(f"    + Added specific match: {person_name}")
                
        except Exception as e:
            print(f"  [Title Search] Error: {e}")
        
        return candidates

    def _search_by_name_alias(self, entity: str, keywords: List[str]) -> List[Dict]:
        """Search 2 chiều: Tìm Name nodes → lấy Person liên quan."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            candidates = []
            search_terms = [entity] + [k for k in keywords if len(k) > 2][:5]
            
            for term in search_terms:
                result = session.run("""
                    MATCH (n:Name)
                    WHERE toLower(n.value) CONTAINS toLower($term)
                       OR toLower(n.name_type) CONTAINS toLower($term)
                    RETURN n, labels(n)[0] as type
                    LIMIT 5
                """, term=term)
                
                for r in result:
                    n = r["n"]
                    nid = n.element_id
                    if nid not in [c.get("id") for c in candidates]:
                        person_result = session.run("""
                            MATCH (n:Name)-[]-(p:Person)
                            WHERE elementId(n) = $nid
                            RETURN elementId(p) as person_eid, p.name as person_name
                            LIMIT 1
                        """, nid=nid)
                        
                        for pr in person_result:
                            candidates.append({
                                "id": pr["person_eid"],
                                "type": "Person",
                                "name": pr["person_name"],
                                "via_name": n.get("value", ""),
                                "properties": dict(n),
                                "score": 1.5,
                                "source": "name_alias"
                            })
            
            return candidates

    def _search_name_alias_for_entity(self, entity: str, intent: str) -> List[Dict]:
        """Tìm alias/tên thật của entity dựa trên intent."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            candidates = []
            
            # Map intent → name_type
            intent_to_nametype = {
                "birth_name": ["birth_name", "birthname", "tên khai sinh"],
                "real_name": ["real_name", "birth_name"],
                "temple_name": ["temple_name", "tên húy"],
                "original_name": ["original_name", "tên gốc"],
                "regnal_name": ["regnal_name", "niên hiệu"],
            }
            name_types = intent_to_nametype.get(intent, [intent])
            
            # Tìm Person - case-insensitive
            person_result = session.run("""
                MATCH (p:Person)
                WHERE toLower(p.name) CONTAINS toLower($entity)
                   OR toLower(p.full_name) CONTAINS toLower($entity)
                   OR toLower(p.alias) CONTAINS toLower($entity)
                RETURN elementId(p) as peid, p.name as pname
                LIMIT 3
            """, entity=entity)
            
            for pr in person_result:
                pid = pr["peid"]
                pname = pr["pname"]
                
                # Lấy TẤT CẢ Name nodes
                all_names_result = session.run("""
                    MATCH (p:Person)-[r]-(n:Name)
                    WHERE elementId(p) = $peid
                    RETURN n.value as name_value, n.name_type as name_type, type(r) as rel_type
                    LIMIT 10
                """, peid=pid)
                
                names = []
                for nr in all_names_result:
                    nv = nr.get("name_value", "")
                    if nv:
                        names.append({
                            "value": nv,
                            "type": nr.get("name_type", ""),
                            "rel": nr.get("rel_type", "")
                        })
                
                if names:
                    candidates.append({
                        "id": pid,
                        "type": "Person",
                        "name": pname,
                        "score": 2.0,
                        "source": f"name_alias:{intent}",
                        "all_names": names
                    })
            
            return candidates

    def _search_relationship_for_entity(self, entity: str, intent: str) -> List[Dict]:
        """Tìm relationship SUCCESSOR_OF/PREDECESSOR_OF cho entity."""
        from retriever.graph_retriever import GraphRetriever
        retriever = GraphRetriever(self.graph_db)
        
        try:
            rel_result = retriever.retrieve_by_relationship_type(entity, intent)
            candidates = []
            
            targets_with_year = []  # For SPOUSE_OF filtering
            
            for target in rel_result.get("targets", []):
                target_props = target.get("target", {})
                rel_props = target.get("relationship_properties", {})
                tid = target_props.get("id") or target_props.get("name", "")
                
                # === FIX: For SPOUSE_OF, prioritize and limit to current marriages ===
                if intent.upper() == "SPOUSE_OF":
                    # Collect spouses with start_year (current/documented marriages)
                    if rel_props.get("start_year"):
                        targets_with_year.append({
                            "target": target_props,
                            "rel_props": rel_props,
                            "tid": tid,
                            "direction": target.get("direction", "outgoing"),
                            "start_year": rel_props.get("start_year", 0)
                        })
                    continue  # Skip ex-spouses without start_year
                
                if tid:
                    candidates.append({
                        "id": tid,
                        "type": "Person",
                        "name": target_props.get("name", ""),
                        "properties": target_props,
                        "score": 2.5,
                        "source": f"relationship:{intent}",
                        "relationship": intent,
                        "direction": target.get("direction", "outgoing"),
                        "relationship_properties": rel_props
                    })
            
            # For SPOUSE_OF: only add the MOST RECENT spouse (highest start_year)
            if intent.upper() == "SPOUSE_OF" and targets_with_year:
                # Sort by start_year DESC and take the first (most recent)
                targets_with_year.sort(key=lambda x: x["start_year"], reverse=True)
                most_recent = targets_with_year[0]
                candidates.append({
                    "id": most_recent["tid"],
                    "type": "Person",
                    "name": most_recent["target"].get("name", ""),
                    "properties": most_recent["target"],
                    "score": 2.5,
                    "source": "relationship:SPOUSE_OF",
                    "relationship": "SPOUSE_OF",
                    "direction": most_recent["direction"],
                    "relationship_properties": most_recent["rel_props"]
                })
            
            return candidates
        except Exception as e:
            print(f"  [Relationship] Error searching {intent} for {entity}: {e}")
            return []

    def _fulltext_search(self, entity: str, keywords: List[str], include_events: bool = False) -> List[Dict]:
        """Fulltext search - primary entry point. LUÔN bao gồm all_names."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            candidates = []
            search_terms = [entity] + [k for k in keywords if len(k) > 2][:3]

            print(f"  [Fulltext] Searching with terms: {search_terms}")

            # === FIX: Ưu tiên EXACT MATCH cho Person nodes ===
            # Tìm exact match TRƯỚC với score cao hơn
            for term in search_terms:
                exact_result = session.run("""
                    MATCH (p:Person)
                    WHERE toLower(p.name) = toLower($term)
                       OR toLower(p.full_name) = toLower($term)
                    RETURN p, 'exact' as match_type
                    LIMIT 5
                """, term=term)
                
                exact_count = 0
                for r in exact_result:
                    exact_count += 1
                    node = r["p"]
                    nid = node.element_id
                    if nid not in [c.get("id") for c in candidates]:
                        all_names = self._get_all_names_for_node(session, nid)
                        candidates.append({
                            "id": nid,
                            "type": "Person",
                            "name": node.get("name", ""),
                            "properties": dict(node),
                            "score": 3.0,  # EXACT match = score cao nhất
                            "source": "exact_match",
                            "all_names": all_names
                        })
                if exact_count > 0:
                    print(f"  [Fulltext] EXACT match: found {exact_count} Person(s)")

            # Thử fulltext index trước (chỉ khi không có exact match)
            if not any(c.get("source") == "exact_match" for c in candidates):
                try:
                    ft_query = f"{entity}~"
                    result = session.run("""
                        CALL db.index.fulltext.queryNodes("entityIndex", $search_query)
                        YIELD node, score
                        RETURN node, score
                        ORDER BY score DESC
                        LIMIT 10
                    """, search_query=ft_query)
                    
                    ft_count = 0
                    for r in result:
                        ft_count += 1
                        node = r["node"]
                        nid = node.element_id
                        if nid not in [c.get("id") for c in candidates]:
                            candidates.append({
                                "id": nid,
                                "type": list(node.labels)[0] if node.labels else "Unknown",
                                "name": node.get("name", ""),
                                "properties": dict(node),
                                "score": r["score"] * 1.5,  # Boost fulltext score
                                "source": "fulltext",
                                "all_names": self._get_all_names_for_node(session, nid)
                            })
                    if ft_count > 0:
                        print(f"  [Fulltext] Index found: {ft_count} results")
                except Exception as e:
                    print(f"  [Fulltext] Index error: {e}")

            # CONTAINS search (fallback)
            for term in search_terms:
                result = session.run("""
                    MATCH (n)
                    WHERE toLower(n.name) CONTAINS toLower($term)
                       OR toLower(n.value) CONTAINS toLower($term)
                       OR toLower(n.title) CONTAINS toLower($term)
                       OR toLower(n.full_name) CONTAINS toLower($term)
                       OR toLower(n.other_name) CONTAINS toLower($term)
                       OR toLower(n.alias) CONTAINS toLower($term)
                    RETURN n, labels(n)[0] as type
                    LIMIT 10
                """, term=term)
                
                for r in result:
                    n = r["n"]
                    nid = n.element_id
                    ntype = r["type"]
                    
                    if nid not in [c.get("id") for c in candidates]:
                        # Ưu tiên Person nodes với score cao hơn
                        base_score = 1.0
                        if ntype == "Person":
                            base_score = 1.5
                        
                        all_names = self._get_all_names_for_node(session, nid)
                        candidates.append({
                            "id": nid,
                            "type": ntype,
                            "name": n.get("name", "") or n.get("value", ""),
                            "properties": dict(n),
                            "score": base_score,
                            "source": "fulltext_fallback",
                            "all_names": all_names
                        })

            print(f"  [Fulltext] Total candidates: {len(candidates)}")
            
            # NEW: Add Event nodes to fulltext search if include_events=True
            if include_events:
                for term in search_terms:
                    result = session.run("""
                        MATCH (e:Event)
                        WHERE toLower(e.name) CONTAINS toLower($term)
                           OR toLower(e.description) CONTAINS toLower($term)
                           OR toLower(e.location) CONTAINS toLower($term)
                        RETURN e
                        LIMIT 10
                    """, term=term)
                    
                    for r in result:
                        e = r["e"]
                        eid = e.element_id
                        
                        if eid not in [c.get("id") for c in candidates]:
                            candidates.append({
                                "id": eid,
                                "type": "Event",
                                "name": e.get("name", ""),
                                "date": e.get("date", ""),
                                "event_type": e.get("event_type", ""),
                                "description": e.get("description", ""),
                                "location": e.get("location", ""),
                                "participants": e.get("participants", ""),
                                "significance": e.get("significance", ""),
                                "properties": dict(e),
                                "score": 1.2,
                                "source": "fulltext_event",
                                "all_names": []
                            })
            
            return candidates

    def _get_all_names_for_node(self, session, node_eid: str) -> List[Dict]:
        """Lấy tất cả Name nodes liên quan đến một node."""
        all_names = []
        
        try:
            result = session.run("""
                MATCH (n:Name)-[r]-(p)
                WHERE elementId(p) = $peid
                RETURN n.value as name_value, n.name_type as name_type, type(r) as rel_type
            """, peid=node_eid)
            
            for r in result:
                nv = r.get("name_value", "")
                if nv:
                    all_names.append({
                        "value": nv,
                        "type": r.get("name_type", ""),
                        "rel": r.get("rel_type", "")
                    })
        except:
            pass
        
        return all_names

    def _soft_matching_search(self, entity: str, keywords: List[str]) -> List[Dict]:
        """
        Soft matching - bắt property text không index được.
        """
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            candidates = []
            search_texts = [entity.lower()] + [k.lower() for k in keywords if len(k) > 2]

            # Tìm trong biography, description, và các text properties
            result = session.run("""
                MATCH (n)
                WHERE ANY(prop IN keys(n) 
                    WHERE prop IN ['biography', 'description', 'bio', 'content', 'text']
                      AND n[prop] IS NOT NULL
                      AND toLower(n[prop]) CONTAINS $search)
                RETURN n, labels(n)[0] as type
                LIMIT 10
            """, search=search_texts[0] if search_texts else entity)

            for r in result:
                n = r["n"]
                nid = n.element_id
                # Lấy all_names
                all_names = self._get_all_names_for_node(session, nid)
                
                candidates.append({
                    "id": nid,
                    "type": r["type"],
                    "name": n.get("name", "") or n.get("value", ""),
                    "properties": dict(n),
                    "score": 0.7,
                    "source": "soft_match",
                    "all_names": all_names
                })

            return candidates

    def _vector_search(self, query: str) -> List[Dict]:
        """
        Vector search - semantic fallback.
        Query trên tất cả vector indexes: PersonVectorIndex, NameVectorIndex, DynastyVectorIndex.
        """
        model = self._get_semantic_model()
        if not model:
            print("  [Vector] Model not available (sentence-transformers not installed)")
            return []

        try:
            query_embedding = model.encode(query).tolist()
            
            with self.graph_db.driver.session(database=self.graph_db.database) as session:
                candidates = []
                
                # Danh sách vector indexes
                vector_indexes = [
                    "PersonVectorIndex",
                    "NameVectorIndex", 
                    "DynastyVectorIndex"
                ]
                
                for idx_name in vector_indexes:
                    try:
                        result = session.run(f"""
                            CALL db.index.vector.queryNodes("{idx_name}", 10, $embedding)
                            YIELD node, score
                            RETURN node, score
                            ORDER BY score DESC
                            LIMIT 5
                        """, embedding=query_embedding)
                        
                        for r in result:
                            node = r["node"]
                            candidates.append({
                                "id": node.element_id,
                                "type": list(node.labels)[0] if node.labels else "Unknown",
                                "name": node.get("name", "") or node.get("value", ""),
                                "properties": dict(node),
                                "score": r["score"],
                                "source": "vector"
                            })
                    except Exception as e:
                        # Index có thể chưa tồn tại, bỏ qua
                        pass
                
                if candidates:
                    print(f"  [Vector] Found {len(candidates)} results")
                
                # Sort theo score
                candidates.sort(key=lambda x: x["score"], reverse=True)
                return candidates[:10]
                
        except Exception as e:
            print(f"  [Vector] Error: {e}")
            return []

    # =========================================================================
    # 3. GRAPH EXPANSION (DB-driven) - FULL BIDIRECTIONAL EXPANSION
    # =========================================================================

    def _expand_graph(self, candidates: List[Dict]) -> List[Dict]:
        if not candidates:
            return []

        MAX_TOTAL_NODES = 200
        candidate_ids = [c["id"] for c in candidates[:50]]

        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            # QUERY 1: Giữ nguyên logic tìm neighbor của em
            batch_query = """
            UNWIND $cids AS cid
            MATCH (center) WHERE elementId(center) = cid
            MATCH (center)-[r*1..1]-(neighbor)
            WHERE NOT elementId(neighbor) = cid
            WITH DISTINCT neighbor
            LIMIT $total_limit
            RETURN elementId(neighbor) AS nid, labels(neighbor)[0] AS ntype
            """
            
            nodes_to_fetch = session.run(batch_query, cids=candidate_ids, total_limit=MAX_TOTAL_NODES)
            
            expanded = {}
            person_ids = []

            for record in nodes_to_fetch:
                if record["ntype"] == "Person":
                    person_ids.append(record["nid"])
                else:
                    # Tạm thời bỏ qua các node khác hoặc xử lý đơn giản để không delay
                    expanded[record["nid"]] = {"id": record["nid"], "type": record["ntype"]}

            # FIX LỖI: Thay vì gọi hàm không tồn tại, mình dùng chính hàm _get_person_context cũ của em
            # nhưng chạy trong vòng lặp (vì em muốn giữ nguyên query đơn lẻ để báo cáo)
            if person_ids:
                for pid in person_ids:
                    if len(expanded) >= MAX_TOTAL_NODES:
                        break
                    # Gọi lại đúng hàm em đã viết, không đẻ thêm hàm mới
                    person_data = self._get_person_context(session, pid)
                    if person_data:
                        expanded[pid] = person_data

            return list(expanded.values())
    
    def _get_person_context(self, session, person_eid: str) -> Dict:
        """
        PHIÊN BẢN BẢO TỒN 100% LOGIC CỦA NHÂN.
        Gom 5 query thành 1 nhưng giữ nguyên mọi thuộc tính và logic format.
        """
        mega_query = """
        MATCH (p:Person) WHERE elementId(p) = $peid
        RETURN p {
            .*, // <-- Hốt TRỌN BỘ: nickname, reign_duration, personality, father, mother...
            all_names_raw: [(p)-[r]-(n:Name) | {
                value: n.value, type: n.name_type, rel: type(r)
            }],
            related_nodes: [(p)-[r]-(rel) WHERE NOT rel:Person AND NOT rel:Name | {
                name: rel.name, type: labels(rel)[0], rel_type: type(r),
                is_outgoing: startNode(r) = p, 
                year: rel.year, month: rel.month, age: rel.age, 
                description: rel.description, date: rel.date,
                // Lấy người liên quan đến Event (Logic bổ sung cực hay của em)
                event_persons: [(rel)-[er]-(p2:Person) WHERE p2 <> p | p2.name][0..5]
            }][0..100],
            family: [(p)-[r]-(f:Person) | {
                name: f.name, rel_type: type(r), 
                is_outgoing: startNode(r) = p, rel_props: properties(r)
            }][0..30]
        } AS full_data
        """
        
        result = session.run(mega_query, peid=person_eid)
        record = result.single()
        if not record: return {}
        
        data = record["full_data"]
        
        # --- 1. GIỮ NGUYÊN: Khởi tạo và đổ dữ liệu cơ bản ---
        context = { "id": person_eid, "type": "Person", "all_names": [], "related": [] }
        
        # Danh sách này là những gì em đang lo bị thiếu đây:
        fields = [
            "name", "full_name", "other_name", "birth_name", "nickname", "alias", 
            "description", "role", "title", "birth_date", "death_date", 
            "birth_year", "death_year", "reign_start", "reign_end", 
            "reign_duration", "personality", "adoptive_father", "father", "mother"
        ]
        for f in fields:
            # data.get(f, "") đảm bảo nếu node có thì lấy, không có thì để rỗng y hệt code cũ
            context[f] = data.get(f, "") or ""

        # --- 2. GIỮ NGUYÊN: Xử lý Names ---
        for n in data.get("all_names_raw", []):
            context["all_names"].append({"value": n["value"], "type": n["type"], "rel": n["rel"]})

        # --- 3. GIỮ NGUYÊN: Logic format chi tiết (rel_detail) ---
        for rr in data.get("related_nodes", []):
            rel_text = self._format_relationship(rr["rel_type"], rr["is_outgoing"], rr["name"])
            
            # ĐÂY LÀ ĐOẠN EM LO BỊ THIẾU:
            parts = []
            if rr.get("date"): parts.append(f"ngày: {rr['date']}")
            if rr.get("month"): parts.append(f"tháng: {rr['month']}")
            if rr.get("year"): parts.append(f"năm: {rr['year']}")
            if rr.get("age"): parts.append(f"tuổi: {rr['age']}")
            rel_detail = f" [{', '.join(parts)}]" if parts else ""
            
            related_persons = ""
            if rr.get("event_persons"):
                related_persons = f" - Người liên quan: {', '.join(rr['event_persons'])}"

            context["related"].append({
                "name": rr["name"], "type": rr["type"], "rel": rel_text,
                "detail": rel_detail, "related_persons": related_persons,
                "description": rr.get("description", "") or "",
                "year": rr.get("year", ""), "month": rr.get("month", ""), "date": rr.get("date", "")
            })

        # --- 4. GIỮ NGUYÊN: Logic Family (rel_props) ---
        for f in data.get("family", []):
            rel_text = self._format_relationship(f["rel_type"], f["is_outgoing"], f["name"], f["rel_props"])
            context["related"].append({
                "name": f["name"], "type": "Person", "rel": rel_text, "rel_props": f["rel_props"]
            })

        return context
    
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
        """
        LLM filter context - GỬI TẤT CẢ context để tránh hallucination.
        
        FIX: Không filter quá mức, gửi hết context cho answer generation.
        """
        if not candidates:
            return ""

        entity = query_info.get("entity", "")
        intent = query_info.get("intent", "")
        
        # Format candidates thành text
        context_text = self._format_candidates(candidates, main_entity_name=entity)
        
        # DEBUG: Print context trước khi gửi cho LLM
        print(f"\n  [DEBUG] === CONTEXT FILTERING DEBUG ===")
        print(f"  Entity: {entity}")
        print(f"  Intent: {intent}")
        print(f"  Total candidates: {len(candidates)}")
        print(f"  [DEBUG] Raw context length: {len(context_text)} chars")

        # FIX: GỬI TẤT CẢ CONTEXT - không filter
        # LLM filter không cần thiết và gây ra hallucination
        # Trả về toàn bộ context để answer generation tự tìm thông tin
        
        print(f"  [DEBUG] Sending FULL context to answer generation (no LLM filter)")
        return context_text

    def _format_candidates(self, candidates: List[Dict], main_entity_name: str = None) -> str:
        """Format candidates thành text readable - ƯU TIÊN main entity."""
        lines = []
        
        # === FIX: Ưu tiên main entity hiển thị ĐẦU TIÊN ===
        main_entity_lines = []
        other_lines = []
        
        main_entity_id = None
        if main_entity_name:
            for c in candidates:
                cname = c.get("name", "").lower()
                all_names = c.get("all_names", [])
                if (cname and main_entity_name.lower() in cname) or \
                   any(main_entity_name.lower() in n.get("value", "").lower() for n in all_names):
                    main_entity_id = c.get("id")
                    break
        
        for c in candidates:
            node_type = c.get("type", "Unknown")
            name = c.get("name", "N/A")
            
            line = f"\n[{node_type}] {name}"
            
            # Birth/Death/Reign info + Title/Alias + ALL Critical Properties
            for key in ["role", "description", "birth_place", "organization", "action", "phong_vuong_year", "title", "alias", "other_name", "birth_name", "birth_date", "birth_year", "death_date", "death_year", "reign_start", "reign_end", "reign_duration", "reign_duration_days", "reign_length_days", "duration_days", "personality", "adoptive_father", "father", "mother"]:
                val = c.get(key, "") or c.get("properties", {}).get(key, "")
                if val:
                    line += f"\n  {key}: {val}"
            
            # All Names
            all_names = c.get("all_names", [])
            if all_names:
                line += "\n  All Names:"
                for an in all_names:
                    if an.get('value'):
                        line += f"\n    - {an['value']} [{an.get('type', '')}]"
            
            # CRITICAL: Ensure reign_duration is always shown
            reign_duration = c.get("reign_duration") or c.get("properties", {}).get("reign_duration")
            if reign_duration and "reign_duration" not in line:
                line += f"\n  reign_duration: {reign_duration}"
            
            # Properties (exclude those already displayed above)
            all_props = c.get("properties", {})
            if all_props:
                line += "\n  Properties:"
                excluded_props = {"role", "description", "birth_place", "organization", "action", "phong_vuong_year", 
                                 "title", "alias", "other_name", "birth_name", "birth_date", "birth_year", 
                                 "death_date", "death_year", "reign_start", "reign_end", "reign_duration", 
                                 "reign_duration_days", "reign_length_days", "duration_days", "personality",
                                 "adoptive_father", "father", "mother"}
                for prop, val in all_props.items():
                    if val and prop not in excluded_props:
                        line += f"\n    - {prop}: {val}"
            
            # Related - FIX: Hiển thị THÊM chi tiết (year, month, age) cho Event nodes
            related = c.get("related", [])
            if related:
                line += "\n  Related:"
                for r in related[:50]:  # Tăng từ 10 lên 50
                    rel_name = r.get('name', 'N/A')
                    rel_text = r.get('rel', '')
                    
                    # Thêm chi tiết nếu có (đặc biệt cho Event: year, month, age)
                    detail_parts = []
                    if r.get('year'):
                        detail_parts.append(f"năm {r['year']}")
                    if r.get('month'):
                        detail_parts.append(f"{r['month']}")
                    if r.get('age'):
                        detail_parts.append(f"tuổi {r['age']}")
                    if r.get('date'):
                        detail_parts.append(f"ngày {r['date']}")
                    if r.get('description'):
                        detail_parts.append(f"{r['description']}")
                    
                    detail_str = ""
                    if detail_parts:
                        detail_str = f" - {', '.join(detail_parts)}"
                    
                    # Hiển thị người liên quan đến Event (nếu có)
                    related_persons_str = r.get('related_persons', '')
                    
                    # Ghép thành dòng hoàn chỉnh
                    if rel_text:
                        line += f"\n    - {rel_name}: {rel_text}{detail_str}{related_persons_str}"
                    else:
                        # Fallback: dùng type node, không dùng relationship type bằng tiếng Anh
                        node_type = r.get('type', '')
                        if node_type:
                            line += f"\n    - {rel_name} ({node_type}){detail_str}{related_persons_str}"
                        else:
                            line += f"\n    - {rel_name}{detail_str}{related_persons_str}"
            
            # Phân chia: main entity vs others
            if c.get("id") == main_entity_id:
                main_entity_lines.append(line)
            else:
                other_lines.append(line)
        
        # Main entity luôn ở ĐẦU TIÊN
        lines = main_entity_lines + other_lines
        
        return "\n".join(lines)

    # =========================================================================
    # 5. ANSWER GENERATION (LLM)
    # =========================================================================

    def _generate_answer(self, query_info: Dict, context: str) -> str:
        """Generate answer từ context đã lọc - with real-time streaming."""
        if not context:
            return self._no_data_answer(query_info)

        # Stream answer in real-time
        answer_text = ""
        print("  📡 Streaming response from LLM...\n")
        
        default_temp = float(os.getenv('LLM_TEMPERATURE', '0.1'))
        for chunk in self.answer_generator.generate_answer_stream(
            question=query_info["original_question"],
            context=context,
            temperature=default_temp  # Temperature from env for consistency
        ):
            print(chunk, end="", flush=True)
            answer_text += chunk
        
        print()  # Newline after streaming
        return answer_text

    def _no_data_answer(self, query_info: Dict) -> str:
        """Fallback khi không có data."""
        return """Không tìm thấy thông tin trong dữ liệu.

Gợi ý:
- Kiểm tra lại chính tả tên nhân vật
- Thử hỏi theo cách khác: "X là ai?" thay vì "tên thật của X"
- Nhân vật có thể chưa được thêm vào database"""

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
        
        # Find the main Person candidate (highest score)
        main_person = None
        for c in candidates:
            if c.get('type') == 'Person':
                main_person = c.get('name', '')
                break
        
        # Append active person to answer for .NET backend to parse
        if main_person:
            print(f"Answer:\n{answer}\n")
            print(f"Active person: {main_person}")
            return f"{answer}\n\nActive person: {main_person}"
        elif query_info.get("entity"):
            print(f"Answer:\n{answer}\n")
            print(f"Active person: {query_info['entity']}")
            return f"{answer}\n\nActive person: {query_info['entity']}"
        else:
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
# STANDALONE FUNCTION (for streamlit)
# =============================================================================

def ask_agent(question: str) -> str:
    """Standalone function for Streamlit UI."""
    pipeline = QueryPipeline()
    return pipeline.process_query(question)
