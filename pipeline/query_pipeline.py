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

        # 1.2 Intent detection
        intent = "identity"  # default
        for keyword, mapped_intent in self.INTENT_MAPPING.items():
            if keyword in question_lower:
                intent = mapped_intent
                break

        # 1.3 Target type inference (simple rule)
        target_type = self._infer_target_type(question_lower, intent)

        return {
            "entity": entity,
            "intent": intent,
            "target_type": target_type,
            "keywords": keywords,
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
                for r in result:
                    w1 = r.get("word1", "")
                    w2 = r.get("word2", "")
                    if w1 and w2:
                        if w1 not in synonym_map:
                            synonym_map[w1] = set()
                        if w2 not in synonym_map:
                            synonym_map[w2] = set()
                        synonym_map[w1].add(w2)
                        synonym_map[w2].add(w1)
                
                # Convert set to list
                for word, synonyms in synonym_map.items():
                    self._synonym_cache[word] = list(synonyms)
                
                print(f"  [Synonyms] Loaded {len(self._synonym_cache)} synonyms from DB")
                return self._synonym_cache
                
        except Exception as e:
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
        """Trích xuất entity từ câu hỏi."""
        patterns = [
            r'(?:của|tên|ai là|gì là)\s+(.+?)(?:\?|$)',  # "tên của X", "X là ai"
            r'^(.+?)(?:\s+là\s+ai|\s+là\s+gì|\s+ở\s+đâu)',  # "X là ai"
            r'\"(.+?)\"',  # "X"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question)
            if match:
                return match.group(1).strip()
        
        # Fallback: word segment và lấy tên riêng
        if WORD_SEG_AVAILABLE:
            words = underthesea.word_tokenize(question)
            for i, w in enumerate(words):
                if w[0].isupper() if w else False:
                    # Ghép với từ tiếp theo nếu là part of name
                    if i + 1 < len(words) and words[i + 1][0].isupper():
                        return f"{w} {words[i + 1]}"
                    return w
        
        return question.strip()

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

    def _get_query_variants(self, question: str) -> List[str]:
        """
        Tạo các biến thể của câu hỏi để search hiệu quả hơn.
        VD: "Bảo Đại lên ngôi năm nào?" → ["Bảo Đại đăng quang", "Bảo Đại lên ngôi"]
        """
        variants = [question]

        question_lower = question.lower()

        # Tìm các synonym trong câu hỏi và tạo biến thể
        for key, synonyms in self.QUERY_VARIANTS.items():
            if key in question_lower:
                # Thay thế bằng từng synonym
                for syn in synonyms:
                    variant = question_lower.replace(key, syn)
                    if variant != question_lower:
                        variants.append(variant)
                # Cũng thử kết hợp với tên người
                entity = self._extract_entity(question)
                if entity:
                    for syn in synonyms[:2]:  # Chỉ lấy 2 synonym đầu
                        variants.append(f"{entity} {syn}")

        return list(set(variants))[:5]  # Giới hạn 5 variants

    def _infer_target_type(self, question_lower: str, intent: str) -> str:
        """Infer target node type từ câu hỏi."""
        if any(w in question_lower for w in ['triều', 'đại']):
            return "Dynasty"
        if any(w in question_lower for w in ['sự kiện', 'chiến tranh', 'trận']):
            return "Event"
        if any(w in question_lower for w in ['vua', 'hoàng đế', 'nhà', 'thái tử']):
            return "Person"
        return "Person"  # default

    # =========================================================================
    # 2. CANDIDATE RETRIEVAL (DB-driven 100%)
    # =========================================================================

    def _retrieve_candidates(self, query_info: Dict) -> List[Dict]:
        """
        Tìm kiếm candidates - DB-driven, KHÔNG dùng LLM.
        Search 2 chiều + Query variants + NAME-FIRST cho alias queries:
        1. Nếu hỏi về "tên thật/tên khai sinh" → Tìm Name nodes TRƯỚC
        2. Tìm Name nodes (alias, tên khác)
        3. Tìm với query variants
        4. Tìm Person nodes
        5. Kết hợp kết quả

        Returns:
            List of candidate nodes với scores
        """
        entity = query_info.get("entity", "")
        keywords = query_info.get("keywords", [])
        intent = query_info.get("intent", "")
        original_question = query_info.get("original_question", entity)

        candidates = []
        seen_ids = set()

        # === 0.0: SYNONYM EXPANSION (DB-driven) ===
        # VD: ["đăng quang"] → ["đăng quang", "lên ngôi", "đăng cơ", ...]
        expanded_keywords = self._expand_query_with_synonyms(keywords)
        if expanded_keywords != keywords:
            print(f"  [Synonyms] Expanded: {keywords} → {expanded_keywords}")

        # === 0.1: NAME-FIRST SEARCH cho "tên thật/birth_name" intent ===
        name_intents = ["birth_name", "real_name", "temple_name", "original_name", "regnal_name"]
        if intent in name_intents:
            name_first_candidates = self._search_name_alias_for_entity(entity, intent)
            for c in name_first_candidates:
                if c.get("id") not in seen_ids:
                    c["score"] = 2.0
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === 0.2: NAME-FIRST SEARCH (tìm alias/tên khác) ===
        name_candidates = self._search_by_name_alias(entity, keywords)
        for c in name_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

        # === 2.1: FULLTEXT SEARCH với EXPANDED keywords ===
        # Tìm cả entity và synonyms
        ft_candidates = self._fulltext_search(entity, expanded_keywords)
        for c in ft_candidates:
            if c.get("id") not in seen_ids:
                candidates.append(c)
                seen_ids.add(c.get("id"))

        # === 2.2: SOFT MATCHING (fallback) với synonyms ===
        if len(candidates) < 3:
            soft_candidates = self._soft_matching_search(entity, expanded_keywords)
            for c in soft_candidates:
                if c.get("id") not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

        # === 2.3: VECTOR SEARCH (fallback) ===
        if len(candidates) < 3 and SEMANTIC_AVAILABLE:
            vec_candidates = self._vector_search(entity)
            for c in vec_candidates:
                if c.get("id") not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c.get("id"))

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

            # Thử fulltext index trước
            try:
                result = session.run("""
                    CALL db.index.fulltext.queryNodes("entityIndex", $query)
                    YIELD node, score
                    RETURN node, score
                    ORDER BY score DESC
                    LIMIT 10
                """, query=f"{entity}~")
                
                for r in result:
                    node = r["node"]
                    nid = node.element_id
                    candidates.append({
                        "id": nid,
                        "type": list(node.labels)[0] if node.labels else "Unknown",
                        "name": node.get("name", ""),
                        "properties": dict(node),
                        "score": r["score"],
                        "source": "fulltext",
                        "all_names": self._get_all_names_for_node(session, nid)
                    })
                
                if candidates:
                    return candidates
            except:
                pass  # Fallback to CONTAINS

            # Fallback: CONTAINS search
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
                    LIMIT 5
                """, term=term)
                
                for r in result:
                    n = r["n"]
                    nid = n.element_id
                    ntype = r["type"]
                    
                    if nid not in [c.get("id") for c in candidates]:
                        all_names = self._get_all_names_for_node(session, nid)
                        candidates.append({
                            "id": nid,
                            "type": ntype,
                            "name": n.get("name", "") or n.get("value", ""),
                            "properties": dict(n),
                            "score": 1.0,
                            "source": "fulltext_fallback",
                            "all_names": all_names
                        })

            return candidates

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
                
                # Sort theo score
                candidates.sort(key=lambda x: x["score"], reverse=True)
                return candidates[:10]
                
        except Exception as e:
            print(f"❌ Vector search error: {e}")
            return []

    # =========================================================================
    # 3. GRAPH EXPANSION (DB-driven) - FULL BIDIRECTIONAL EXPANSION
    # =========================================================================

    def _expand_graph(self, candidates: List[Dict]) -> List[Dict]:
        """
        Expand graph từ candidates - LẤY TẤT CẢ related nodes.
        
        Ví dụ:
        - Event → lấy Person (người tham gia, chỉ huy, nạn nhân)
        - Person → lấy Events, Names, Dynasties
        - Dynasty → lấy Persons thuộc triều đình
        - Query "Ai làm XYZ?" → Event → Person
        """
        if not candidates:
            return []

        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            expanded = {}
            
            # === Phase 1: Thu thập TẤT CẢ elementIds từ candidates ===
            all_ids = {}  # elementId -> {type, name, via_name}
            
            for c in candidates:
                cid = c["id"]
                ctype = c["type"]
                cname = c.get("name", "")
                via_name = c.get("via_name", "")
                
                all_ids[cid] = {
                    "type": ctype,
                    "name": cname,
                    "via_name": via_name
                }
            
            # === Phase 2: EXPAND NEIGHBORHOOD (2-hop) - Lấy tất cả related nodes ===
            for cid, cinfo in all_ids.items():
                ctype = cinfo["type"]
                
                # Query lấy neighborhood 2-hop
                neighborhood_result = session.run("""
                    MATCH path = (center)-[*1..2]-(neighbor)
                    WHERE elementId(center) = $cid
                    AND NOT elementId(neighbor) = $cid
                    RETURN neighbor, relationships(path) as rels
                    LIMIT 50
                """, cid=cid)
                
                for nr in neighborhood_result:
                    neighbor = nr["neighbor"]
                    rels = nr["rels"]
                    
                    nid = neighbor.element_id
                    ntype = list(neighbor.labels)[0] if neighbor.labels else "Unknown"
                    nname = neighbor.get("name", "") or neighbor.get("value", "")
                    
                    # Xác định relationship type
                    rel_type = type(rels[0]).__name__ if rels else ""
                    
                    # Ưu tiên Person nodes
                    if ntype == "Person" and nid not in expanded:
                        expanded[nid] = self._get_person_context(session, nid)
                    elif ntype == "Event" and nid not in expanded:
                        # Xử lý Event nodes - lấy properties và related
                        node_props = dict(neighbor)
                        expanded[nid] = {
                            "id": nid,
                            "type": ntype,
                            "name": nname,
                            "rel": rel_type,
                            "all_names": [],
                            "related": [],
                            "properties": node_props
                        }
                        # Lấy related nodes của Event
                        event_related = session.run("""
                            MATCH (e)-[r]->(related)
                            WHERE elementId(e) = $eid
                            RETURN related.name as rel_name, 
                                   labels(related)[0] as rel_type,
                                   type(r) as relationship
                            LIMIT 20
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
                        # Lấy TẤT CẢ properties của neighbor node
                        node_props = dict(neighbor)
                        expanded[nid] = {
                            "id": nid,
                            "type": ntype,
                            "name": nname,
                            "rel": rel_type,
                            "all_names": [],
                            "related": [],
                            "properties": node_props
                        }
            
            # === Phase 3: Ensure Person context (nếu có Event nhưng chưa có Person) ===
            for cid, cinfo in all_ids.items():
                if cinfo["type"] == "Event":
                    person_result = session.run("""
                        MATCH (e)-[r]-(p:Person)
                        WHERE elementId(e) = $eid
                        RETURN DISTINCT elementId(p) as pid
                        LIMIT 10
                    """, eid=cid)
                    
                    for pr in person_result:
                        pid = pr["pid"]
                        if pid not in expanded:
                            expanded[pid] = self._get_person_context(session, pid)
            
            return list(expanded.values())
    
    def _get_person_context(self, session, person_eid: str) -> Dict:
        """Lấy full context cho một Person node."""
        person_result = session.run("""
            MATCH (p:Person)
            WHERE elementId(p) = $peid
            RETURN p.name as name, p.full_name as full_name, p.other_name as other_name,
                   p.birth_name as birth_name, p.alias as alias,
                   p.description as description, p.role as role, p.title as title
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
        
        # Lấy related nodes (events, dynasties, positions...)
        related_result = session.run("""
            MATCH (p:Person)-[r]->(related)
            WHERE elementId(p) = $peid
            RETURN related.name as rel_name, 
                   labels(related)[0] as rel_type,
                   type(r) as relationship
            LIMIT 30
        """, peid=person_eid)
        
        for rr in related_result:
            rln = rr.get("rel_name", "")
            if rln:
                context["related"].append({
                    "name": rln,
                    "type": rr.get("rel_type", ""),
                    "rel": rr.get("relationship", "")
                })
        
        return context

    # =========================================================================
    # 4. CONTEXT FILTERING (LLM - CHỈ filter, KHÔNG search)
    # =========================================================================

    def _filter_context(self, query_info: Dict, candidates: List[Dict]) -> str:
        """
        LLM filter context - CHỈ chọn thông tin liên quan từ candidates.
        """
        if not candidates:
            return ""

        # Format candidates thành text
        context_text = self._format_candidates(candidates)
        
        # DEBUG: Print context trước khi gửi cho LLM
        print(f"\n  [DEBUG] Context preview (first 500 chars):")
        print(f"  {context_text[:500] if context_text else 'EMPTY'}")
        print(f"  [DEBUG] Total candidates: {len(candidates)}")
        print(f"  [DEBUG] Candidate types: {[c.get('type') for c in candidates]}")

        prompt = f"""Bạn là trợ lý RAG - CHỌN thông tin liên quan từ context.

CÂU HỎI: {query_info['original_question']}
ENTITY: {query_info['entity']}
INTENT: {query_info['intent']}
KEYWORDS: {query_info['keywords']}

CONTEXT (từ database - BAO GỒM TẤT CẢ properties):
{context_text}

NHIỆM VỤ:
1. Đọc câu hỏi: "{query_info['original_question']}"
2. Tìm thông tin LIÊN QUAN:
   - Nếu hỏi "Bảo Đại đăng quang năm nào?" → Tìm Event "Đăng quang" của Bảo Đại, lấy property "date"
   - Nếu hỏi "tên thật/birth_name" → Tìm Name nodes có name_type = "birth_name"
   - Nếu hỏi "X là ai?" → Lấy thông tin cơ bản về X
3. Trả về THÔNG TIN ĐẦY ĐỦ (bao gồm cả date nếu có)

QUY TẮC:
- Tìm THẤY thì TRẢ VỀ thông tin (đừng bỏ qua vì nghĩ "không liên quan")
- Nhìn vào properties: date, name, description... đều là thông tin hợp lệ
- Nếu KHÔNG TÌM THẤY → nói "KHÔNG ĐỦ DỮ LIỆU"
- KHÔNG suy đoán hay bịa đặt

Trả về thông tin tìm được, hoặc "KHÔNG ĐỦ DỮ LIỆU"."""

        try:
            response = call_llm(prompt, model='gemini-2.0-flash', temperature=0.1)
            
            # Kiểm tra nếu LLM nói không đủ dữ liệu
            if "KHÔNG ĐỦ DỮ LIỆU" in response.upper():
                return ""
            
            return response.strip()
        except Exception as e:
            print(f"❌ Lỗi filter context: {e}")
            return context_text  # Fallback: return unfiltered

    def _format_candidates(self, candidates: List[Dict]) -> str:
        """
        Format candidates thành text readable - BAO GỒM TẤT CẢ properties.
        VD: Event "Đăng quang" với date: "08-01-1926" phải được hiển thị.
        """
        lines = []
        
        for c in candidates:
            node_type = c.get("type", "Unknown")
            name = c.get("name", "N/A")
            
            line = f"\n[{node_type}] {name}"
            
            # === Tất cả Name nodes - QUAN TRỌNG NHẤT ===
            all_names = c.get("all_names", [])
            if all_names:
                line += "\n  All Names:"
                for an in all_names:
                    name_val = an.get('value', '')
                    name_type = an.get('type', '')
                    rel = an.get('rel', '')
                    if name_val:
                        line += f"\n    - {name_val} [{name_type}]"
            
            # === TẤT CẢ Properties (không giới hạn) ===
            all_props = c.get("properties", {})
            if all_props:
                line += "\n  Properties:"
                for prop, val in all_props.items():
                    if val:  # Chỉ hiển thị properties có giá trị
                        line += f"\n    - {prop}: {val}"
            
            # === Properties trực tiếp (nếu không có trong properties dict) ===
            direct_props = ["full_name", "birth_name", "title", "role", "description", "name", "date"]
            for prop in direct_props:
                if prop not in (all_props or {}) and c.get(prop):
                    line += f"\n    - {prop}: {c.get(prop)}"
            
            # === Related nodes (giới hạn) ===
            related = c.get("related", [])
            if related:
                line += "\n  Related:"
                for r in related[:5]:  # Giới hạn 5
                    line += f"\n    - {r.get('name', 'N/A')} ({r.get('type', '')}) [{r.get('rel', '')}]"
            
            lines.append(line)
        
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
