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
        # Alias patterns
        "còn gọi": "alias",
        "cũng gọi": "alias",
        "hay còn": "alias",
        "bí danh": "nickname",
        "tước hiệu": "title",
        "tước vị": "title",
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
        "vợ": ["phu nhân", "thê tử", "bầu bạn", "người vợ", "bạn đời"],
        "chồng": ["phu quân", "phu nhân", "bầu bạn", "người chồng", "bạn đời"],
        "con": ["hậu duệ", "huyết thống", "đời sau", "con cháu", "nòi giống"],
        "cha": ["phụ thân", "ông", "tổ phụ", "bố", "ba"],
        "mẹ": ["mẫu thân", "bà", "tổ mẫu", "má", "u"],
        "anh em": ["đệ tử", "huynh đệ", "bằng hữu", "bạn bè"],
        "thân": ["bạn thân", "hảo hữu", "tri kỷ", "bằng hữu"],

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

        # 1.1 Rule-based extraction
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
        # === CÁC PATTERN theo thứ tự ưu tiên ===
        patterns = [
            # 1. "X là Y phải không?" - "Bảo Đại là vua cuối cùng của triều Nguyễn phải không?"
            (r'^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+.+?phải\s+không)', 1),
            # 2. "X là ai/gì/ở đâu" - "Bảo Đại là ai?"
            (r'^([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+là\s+ai|\s+là\s+gì|\s+ở\s+đâu)', 1),
            # 3. "X?" - standalone name at start
            (r'^([A-ZÀ-ỹ][a-zà-ỹ]{2,})(?:\s+|$|\?)', 1),
            # 4. "tên/của X?" - "tên thật của Bảo Đại?"
            (r'(?:tên|của|ai là|gì là)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\?|$)', 1),
            # 5. "Sau khi [event], X [verb]" - "Sau khi thoái vị, Bảo Đại giữ..."
            (r',?\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có|ở|sống|mất|năm|nơi|được\s+tổ))', 1),
            # 6. "trong/cho/với X" - "trong Chính phủ VNDCCH"
            (r'(?:trong|cho|với)\s+([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s|$|\?)', 1),
            # 7. "năm 1945, X" - "năm 1945, Bảo Đại"
            (r',\s*([A-ZÀ-ỹ][a-zà-ỹ\s]+?)(?:\s+(?:giữ|làm|được|đóng|là|có))', 1),
        ]

        for pattern, group in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                extracted = match.group(group).strip()
                # Loại bỏ temporal suffixes
                temporal_suffixes = ["sinh", "mất", "đăng", "lên ngôi", "thoái vị", "năm nào", "lúc nào", "ra sao"]
                for suffix in temporal_suffixes:
                    if extracted.lower().endswith(suffix):
                        extracted = extracted[:-len(suffix)].strip()
                # Loại bỏ từ không phải tên
                stopwords = {"ai", "gì", "ở", "đâu", "nào", "chính", "phủ", "việt", "nam", "dân", "chủ", "cộng", "hòa", "vai", "trò", "sau", "khi", "trong", "cho", "với", "năm", "tháng", "ngày", "lời", "bài"}
                words = extracted.split()
                cleaned = " ".join(w for w in words if w.lower() not in stopwords)
                if cleaned and len(cleaned) > 2:
                    return cleaned

        # === Fallback: Word segmentation lấy tên riêng ===
        if WORD_SEG_AVAILABLE:
            words = underthesea.word_tokenize(question)
            entity_words = []
            stopwords = {"sinh", "mất", "năm", "lên", "đăng", "ngày", "tháng", "lúc", "thôi", "là", "ai", "gì", "ở", "đâu", "của", "sau", "khi", "trong", "vai", "trò", "giữ", "được", "chính", "phủ", "việt", "nam", "dân", "chủ", "cộng", "hòa", "?"}
            for w in words:
                if w.lower() in stopwords:
                    continue
                if w[0].isupper() if w else False:
                    entity_words.append(w)
            if entity_words:
                return " ".join(entity_words[:2])  # Lấy 1-2 từ đầu

        # === Fallback cuối: lấy từ hoa đầu tiên ===
        words = question.split()
        for w in words:
            if w[0].isupper() if w else False:
                return w

        return question.strip().rstrip("?").strip()

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
            response = call_llm(prompt, model="gemini-flash-lite", temperature=0.1)  # Low temperature for consistency
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

        # === NAME-ALIAS SEARCH ===
        name_candidates = self._search_by_name_alias(entity, keywords)
        for c in name_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

        # === FULLTEXT SEARCH ===
        ft_candidates = self._fulltext_search(entity, expanded_keywords)
        for c in ft_candidates:
            if c.get("id") not in seen_ids:
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

    def _fulltext_search(self, entity: str, keywords: List[str]) -> List[Dict]:
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
        """
        Expand graph từ candidates - TĂNG GIỚI HẠN để lấy nhiều context hơn.
        
        FIX: Tăng total nodes = 200 (từ 50)
        FIX: Tăng neighbors = 20 (từ 5)
        """
        if not candidates:
            return []

        MAX_TOTAL_NODES = 200  # Tăng từ 50 lên 200
        RESERVE_FOR_MAIN = 30  # Tăng từ 10 lên 30

        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            expanded = {}
            
            # === Tìm và ƯU TIÊN thêm main entity vào expanded ĐẦU TIÊN ===
            main_entity_id = None
            for c in candidates:
                if c.get("score", 0) >= 2.0 and c.get("type") == "Person":
                    main_entity_id = c["id"]
                    break
            
            if not main_entity_id and candidates:
                main_entity_id = candidates[0]["id"]
            
            if main_entity_id:
                main_context = self._get_person_context(session, main_entity_id)
                expanded[main_entity_id] = main_context
                print(f"  [Expand] Main entity added first: {main_context.get('name', 'unknown')}")
            
            # === Phase 1: Thu thập elementIds từ candidates ===
            all_ids = {}
            
            for c in candidates:
                cid = c["id"]
                if cid == main_entity_id:
                    continue
                if len(all_ids) >= MAX_TOTAL_NODES - RESERVE_FOR_MAIN:
                    break
                all_ids[cid] = {
                    "type": c["type"],
                    "name": c.get("name", ""),
                    "via_name": c.get("via_name", "")
                }
            
            # === Phase 2: EXPAND NEIGHBORHOOD (2-hop) ===
            NEIGHBORS_PER_CANDIDATE = 20  # Tăng từ 5 lên 20
            
            for cid, cinfo in all_ids.items():
                if len(expanded) >= MAX_TOTAL_NODES - RESERVE_FOR_MAIN:
                    break
                    
                neighborhood_result = session.run("""
                    MATCH path = (center)-[*1..2]-(neighbor)
                    WHERE elementId(center) = $cid
                    AND NOT elementId(neighbor) = $cid
                    RETURN neighbor, relationships(path) as rels
                    LIMIT $limit
                """, cid=cid, limit=NEIGHBORS_PER_CANDIDATE)
                
                for nr in neighborhood_result:
                    if len(expanded) >= MAX_TOTAL_NODES - RESERVE_FOR_MAIN:
                        break
                        
                    neighbor = nr["neighbor"]
                    rels = nr["rels"]
                    
                    nid = neighbor.element_id
                    ntype = list(neighbor.labels)[0] if neighbor.labels else "Unknown"
                    nname = neighbor.get("name", "") or neighbor.get("value", "")
                    
                    if rels:
                        rel = rels[0]
                        rel_type = type(rel).__name__
                        try:
                            is_outgoing = rel.start_node.element_id == cid
                        except:
                            is_outgoing = True
                    else:
                        rel_type = ""
                        is_outgoing = True
                    
                    if ntype == "Person" and nid not in expanded:
                        expanded[nid] = self._get_person_context(session, nid)
                    elif ntype == "Event" and nid not in expanded:
                        node_props = dict(neighbor)
                        expanded[nid] = {
                            "id": nid, "type": ntype, "name": nname, 
                            "rel_type": rel_type, "is_outgoing": is_outgoing,
                            "all_names": [], "related": [], "properties": node_props
                        }
                        # Event related - lấy nhiều hơn
                        event_related = session.run("""
                            MATCH (e)-[r]-(related)
                            WHERE elementId(e) = $eid
                            RETURN related.name as rel_name, labels(related)[0] as rel_type, type(r) as relationship
                            LIMIT 50
                        """, eid=nid)
                        for er in event_related:
                            rln = er.get("rel_name", "")
                            if rln:
                                expanded[nid]["related"].append({
                                    "name": rln,
                                    "type": er.get("rel_type", ""),
                                    "rel": er.get("relationship", "")
                                })
                    elif nid not in expanded:
                        expanded[nid] = {
                            "id": nid, "type": ntype, "name": nname,
                            "rel_type": rel_type, "is_outgoing": is_outgoing,
                            "all_names": [], "related": [], "properties": dict(neighbor)
                        }
            
            # === Phase 3: Ensure Person context cho Event ===
            for cid, cinfo in all_ids.items():
                if len(expanded) >= MAX_TOTAL_NODES - RESERVE_FOR_MAIN:
                    break
                if cinfo["type"] == "Event":
                    person_result = session.run("""
                        MATCH (e)-[r]-(p:Person)
                        WHERE elementId(e) = $eid
                        RETURN DISTINCT elementId(p) as pid
                        LIMIT 20
                    """, eid=cid)
                    for pr in person_result:
                        if len(expanded) >= MAX_TOTAL_NODES - RESERVE_FOR_MAIN:
                            break
                        pid = pr["pid"]
                        if pid not in expanded:
                            expanded[pid] = self._get_person_context(session, pid)
            
            result = list(expanded.values())
            print(f"  [Expand] Total: {len(result)} nodes")
            return result
    
    def _get_person_context(self, session, person_eid: str) -> Dict:
        """Lấy full context cho một Person node."""
        person_result = session.run("""
            MATCH (p:Person)
            WHERE elementId(p) = $peid
            RETURN p.name as name, p.full_name as full_name, p.other_name as other_name,
                   p.birth_name as birth_name, p.alias as alias,
                   p.description as description, p.role as role, p.title as title,
                   p.birth_date as birth_date, p.death_date as death_date,
                   p.birth_year as birth_year, p.death_year as death_year,
                   p.reign_start as reign_start, p.reign_end as reign_end
        """, peid=person_eid)
        
        context = {
            "id": person_eid,
            "type": "Person",
            "name": "",
            "full_name": "",
            "other_name": "",
            "birth_name": "",
            "nickname": "",
            "alias": "",
            "description": "",
            "role": "",
            "title": "",
            "birth_date": "",
            "death_date": "",
            "birth_year": "",
            "death_year": "",
            "reign_start": "",
            "reign_end": "",
            "all_names": [],
            "related": []
        }
        
        for pr in person_result:
            context["name"] = pr.get("name", "") or ""
            context["full_name"] = pr.get("full_name", "") or ""
            context["other_name"] = pr.get("other_name", "") or ""
            context["birth_name"] = pr.get("birth_name", "") or ""
            context["nickname"] = pr.get("nickname", "") or ""
            context["alias"] = pr.get("alias", "") or ""
            context["description"] = pr.get("description", "") or ""
            context["role"] = pr.get("role", "") or ""
            context["title"] = pr.get("title", "") or ""
            context["birth_date"] = pr.get("birth_date", "") or ""
            context["death_date"] = pr.get("death_date", "") or ""
            context["birth_year"] = pr.get("birth_year", "") or ""
            context["death_year"] = pr.get("death_year", "") or ""
            context["reign_start"] = pr.get("reign_start", "") or ""
            context["reign_end"] = pr.get("reign_end", "") or ""
            break
        
        # Lấy TẤT CẢ Name nodes
        names_result = session.run("""
            MATCH (p:Person)-[r]-(n:Name)
            WHERE elementId(p) = $peid
            RETURN n.value as name_value, n.name_type as name_type, type(r) as rel_type
        """, peid=person_eid)
        
        for nr in names_result:
            nv = nr.get("name_value", "")
            if nv:
                context["all_names"].append({
                    "value": nv,
                    "type": nr.get("name_type", ""),
                    "rel": nr.get("rel_type", "")
                })
        
        # Lấy related nodes - ĐỌC ĐÚNG CHIỀU RELATIONSHIP
        # CHILD_OF: (child)-[:CHILD_OF]->(parent) → "child là con của parent"
        # Mẹ của: (child)-[:CHILD_OF]->(parent) → "parent là mẹ của child"
        # FIX: Lấy THÊM properties của related node (đặc biệt Event có year, month, etc.)
        related_result = session.run("""
            MATCH (p:Person)-[r]-(related)
            WHERE elementId(p) = $peid
            AND NOT related:Person
            RETURN related.name as rel_name, 
                   labels(related)[0] as rel_type,
                   type(r) as relationship,
                   startNode(r).name = p.name as is_outgoing,
                   related.year as rel_year,
                   related.month as rel_month,
                   related.age as rel_age,
                   related.description as rel_description,
                   related.date as rel_date
            LIMIT 100
        """, peid=person_eid)
        
        for rr in related_result:
            rln = rr.get("rel_name", "")
            rel_type = rr.get("relationship", "")
            is_outgoing = rr.get("is_outgoing", True)
            
            if rln:
                # Format relationship text theo đúng chiều
                rel_text = self._format_relationship(rel_type, is_outgoing, rln)
                
                # FIX: Thêm thông tin chi tiết cho Event nodes
                rel_detail = ""
                rel_year = rr.get("rel_year")
                rel_month = rr.get("rel_month")
                rel_age = rr.get("rel_age")
                rel_desc = rr.get("rel_description")
                rel_date = rr.get("rel_date")
                
                if rel_year or rel_month or rel_age or rel_date:
                    parts = []
                    if rel_date:
                        parts.append(f"ngày: {rel_date}")
                    if rel_month:
                        parts.append(f"tháng: {rel_month}")
                    if rel_year:
                        parts.append(f"năm: {rel_year}")
                    if rel_age:
                        parts.append(f"tuổi: {rel_age}")
                    rel_detail = f" [{', '.join(parts)}]"
                
                # FIX: Lấy THÊM thông tin về những người liên quan đến Event này
                # Ví dụ: Event "Thoái vị" có Trần Huy Liệu nhận ấn kiếm
                related_persons = ""
                if rr.get("rel_type") == "Event" or rel_type in ["PERFORMED", "PARTICIPATED_IN", "SIGNED"]:
                    try:
                        # Tìm Person liên quan đến Event này
                        event_name = rln
                        person_result = session.run("""
                            MATCH (e)-[r]-(p:Person)
                            WHERE e.name = $ename AND p.name <> $main_person
                            RETURN p.name as person_name, type(r) as rel_type
                            LIMIT 5
                        """, ename=event_name, main_person=context.get("name", ""))
                        
                        person_list = []
                        for pr in person_result:
                            pn = pr.get("person_name", "")
                            if pn and pn != context.get("name"):
                                person_list.append(pn)
                        
                        if person_list:
                            related_persons = f" - Người liên quan: {', '.join(person_list)}"
                    except:
                        pass
                
                context["related"].append({
                    "name": rln,
                    "type": rr.get("rel_type", ""),
                    "rel": rel_text,
                    "year": rel_year or "",
                    "month": rel_month or "",
                    "age": rel_age or "",
                    "date": rel_date or "",
                    "description": rel_desc or "",
                    "detail": rel_detail,  # Text format cho display
                    "related_persons": related_persons  # Người liên quan đến Event
                })
        
        # Lấy Person-related (family relationships)
        family_result = session.run("""
            MATCH (p:Person)-[r]-(related:Person)
            WHERE elementId(p) = $peid
            RETURN related.name as rel_name, 
                   type(r) as relationship,
                   startNode(r).name = p.name as is_outgoing
            LIMIT 20
        """, peid=person_eid)
        
        for rr in family_result:
            rln = rr.get("rel_name", "")
            rel_type = rr.get("relationship", "")
            is_outgoing = rr.get("is_outgoing", True)
            
            if rln:
                rel_text = self._format_relationship(rel_type, is_outgoing, rln)
                context["related"].append({
                    "name": rln,
                    "type": "Person",
                    "rel": rel_text
                })
        
        return context
    
    def _format_relationship(self, rel_type: str, is_outgoing: bool, target_name: str) -> str:
        """
        Format relationship text theo đúng chiều.
        
        User's Neo4j convention:
        - (Đồng Khánh)-[CHILD_OF]->(Nguyễn Thị Cẩm) 
          → Đồng Khánh là CON CỦA Nguyễn Thị Cẩm
        
        is_outgoing=True: p-[rel]->target → target là parent của p
        is_outgoing=False: p<-[rel]-target → target là parent của p
        """
        # CHILD_OF luôn đi từ child → parent
        # Vậy cả 2 chiều đều có nghĩa: target là cha/mẹ của p
        if rel_type.upper() == "CHILD_OF":
            return f"{target_name} (là cha/mẹ của p)"
        
        if rel_type.upper() == "PARENT_OF":
            if is_outgoing:
                return f"{target_name} (là con của p)"
            else:
                return f"p (là cha/mẹ của {target_name})"
        
        if rel_type.upper() == "FATHER_OF":
            if is_outgoing:
                return f"{target_name} (là con của p)"
            else:
                return f"p (là cha của {target_name})"
        
        if rel_type.upper() == "MOTHER_OF":
            if is_outgoing:
                return f"{target_name} (là con của p)"
            else:
                return f"p (là mẹ của {target_name})"
        
        if rel_type.upper() == "SPOUSE_OF":
            return f"{target_name} (là vợ/chồng của p)"
        
        if rel_type.upper() == "SIBLING_OF":
            return f"{target_name} (là anh chị em của p)"
        
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
            
            # Birth/Death/Reign info
            for key in ["birth_date", "birth_year", "death_date", "death_year", "reign_start", "reign_end"]:
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
            
            # Properties
            all_props = c.get("properties", {})
            if all_props:
                line += "\n  Properties:"
                for prop, val in all_props.items():
                    if val and prop not in ["birth_date", "birth_year", "death_date", "death_year"]:
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
                        line += f"\n    - {rel_name} ({r.get('type', '')}){detail_str}{related_persons_str}"
            
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
        """Generate answer từ context đã lọc."""
        if not context:
            return self._no_data_answer(query_info)

        return self.answer_generator.generate_answer(
            question=query_info["original_question"],
            context=context
        )

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
        filtered_context = self._filter_context(query_info, expanded)
        
        if not filtered_context:
            print("  ⚠️ LLM không tìm thấy context phù hợp")
            return self._no_data_answer(query_info)
        
        print(f"  Context length: {len(filtered_context)} chars")

        # ===== 5. ANSWER GENERATION =====
        print("\n[5/5] Answer Generation (LLM)...")
        answer = self._generate_answer(query_info, filtered_context)
        
        print(f"\n{'='*60}")
        print(f"✅ Answer generated")
        print(f"{'='*60}\n")
        
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
