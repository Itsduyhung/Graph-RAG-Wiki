"""Custom graph extractor - Linh hoạt, cho phép tùy chỉnh prompt và mở rộng properties."""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from graph.builder import GraphBuilder
from graph.storage import GraphDB
from llm.llm_client import call_llm

load_dotenv()


# ============================================================================
# CONFIG - TÙY CHỈNH PROMPT DỄ DÀNG
# ============================================================================

class ExtractionConfig:
    """Cấu hình cho extraction - tùy chỉnh dễ dàng."""
    
    def __init__(
        self,
        # Các properties BẮT BUỘC cho mỗi loại node (dict[str, str] - key: property_name, value: mô tả)
        required_properties: Optional[Dict[str, Dict[str, str]]] = None,
        
        # Các relationship types được phép sử dụng
        allowed_relationship_types: Optional[List[str]] = None,
        
        # Các node types được phép tạo
        allowed_node_types: Optional[List[str]] = None,
        
        # Các properties MẶC ĐỊNH luôn thêm vào (bất kể LLM có nhắc đến hay không)
        default_properties: Optional[Dict[str, Dict[str, Any]]] = None,
        
        # Custom instruction thêm vào cuối prompt
        custom_instruction: str = "",
        
        # Priority target (ưu tiên trích xuất ai)
        priority_target: str = "",
        
        # Có tạo Name nodes cho mỗi Person không
        create_name_nodes: bool = True,
        
        # Có tạo Event nodes không
        create_event_nodes: bool = True,
        
        # Có tạo Location nodes không  
        create_location_nodes: bool = True,
        
        # Có tạo Organization nodes không
        create_organization_nodes: bool = True,
        
        # Có extract temporal info (năm, tháng, ngày) không
        extract_temporal: bool = True,
        
        # Có extract spatial info (địa điểm) không
        extract_spatial: bool = True,
        
        # Có extract quan hệ gia đình không
        extract_family: bool = True,
        
        # Có extract quan hệ chính trị/xã hội không
        extract_social: bool = True,
        
        # Temperature cho LLM (0.0-1.0)
        temperature: float = 0.2,
        
        # Max tokens cho response (None = unlimited)
        max_tokens: Optional[int] = None,
    ):
        # Properties bắt buộc cho mỗi loại node
        self.required_properties = required_properties or {
            "Person": {
                "name": "Tên đầy đủ của người",
                "description": "Mô tả ngắn về người này (ai, làm gì, ý nghĩa)",
            },
            "Event": {
                "name": "Tên sự kiện",
                "description": "Mô tả sự kiện xảy ra gì",
            },
            "Location": {
                "name": "Tên địa điểm",
                "description": "Mô tả địa điểm",
            },
            "Organization": {
                "name": "Tên tổ chức",
                "description": "Mô tả tổ chức",
            },
            "Name": {
                "name": "Tên biến thể",
            },
            "Work": {
                "name": "Tên tác phẩm",
                "description": "Mô tả tác phẩm",
            },
            "Concept": {
                "name": "Tên khái niệm",
                "description": "Mô tả khái niệm",
            },
        }
        
        # Relationship types được phép
        self.allowed_relationship_types = allowed_relationship_types or [
            # Gia đình
            "PARENT_OF", "CHILD_OF", "SPOUSE_OF", "SIBLING_OF", "GRANDPARENT_OF", "GRANDCHILD_OF",
            # Thầy trò
            "MENTOR_OF", "STUDENT_OF", "TEACHER_OF", "TAUGHT_BY",
            # Chính trị/Quân sự
            "MEMBER_OF", "LEADER_OF", "FOUNDED", "FOUNDED_BY", "SUCCEEDED", "PREDECESSOR_OF",
            "COMMANDED", "COMMANDED_BY", "ALLY_OF", "ENEMY_OF", "RIVAL_OF",
            "APPOINTED_BY", "REVOLTED_AGAINST",
            # Sự kiện
            "PARTICIPATED_IN", "WITNESSED", "CAUSED", "LEAD_TO", "RESULTED_IN",
            "PERFORMED", "ORGANIZED", "HOSTED",
            # Ngoại giao
            "MET_WITH", "NEGOTIATED_WITH", "SIGNED_TREATY", "REPRESENTED", "SENT", "RECEIVED_FROM",
            # Địa lý
            "LOCATED_AT", "BORN_IN", "DIED_AT", "RESIDED_IN", "STUDIED_AT", "WORKED_AT",
            "RULED", "RULED_BY", "OCCURRED_IN", "OCCURRED_AT",
            # Tên gọi
            "HAS_NAME", "CALLED_AS", "KNOWN_AS", "ALSO_KNOWN_AS",
            # Thành tựu
            "ACHIEVED", "INVENTED", "CREATED", "AUTHORED", "COMPOSED", "BUILT",
            "RECEIVED_AWARD", "GRANTED_TITLE", "RECEIVED_TITLE",
            # Khác
            "RELATED_TO", "ASSOCIATED_WITH", "BELONGED_TO", "EXPERT_IN", "INTERESTED_IN",
            "SERVED_AS", "WORKED_IN", "MARRIED_TO", "DIVORCED_FROM",
            "INTERACTED_WITH", "INFLUENCED", "INFLUENCED_BY",
        ]
        
        # Node types được phép
        self.allowed_node_types = allowed_node_types or [
            "Person", "Event", "Location", "Organization", "Name",
            "Work", "Concept", "Dynasty", "Era", "Field", "Document",
            "Military", "Award", "Title", "Family", "Group",
        ]
        
        # Properties mặc định luôn thêm
        self.default_properties = default_properties or {}
        
        # Custom instruction
        self.custom_instruction = custom_instruction
        
        # Priority target
        self.priority_target = priority_target
        
        # Flags
        self.create_name_nodes = create_name_nodes
        self.create_event_nodes = create_event_nodes
        self.create_location_nodes = create_location_nodes
        self.create_organization_nodes = create_organization_nodes
        self.extract_temporal = extract_temporal
        self.extract_spatial = extract_spatial
        self.extract_family = extract_family
        self.extract_social = extract_social
        
        # LLM settings
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def to_prompt_section(self) -> str:
        """Convert config thành phần prompt."""
        sections = []
        
        # Required properties
        sections.append("\n【PROPERTIES BẮT BUỘC CHO MỖI NODE】")
        for node_type, props in self.required_properties.items():
            sections.append(f"\n{node_type}:")
            for prop, desc in props.items():
                sections.append(f"  - {prop}: {desc}")
        
        # Allowed relationships
        sections.append("\n【RELATIONSHIP TYPES ĐƯỢC PHÉP】")
        sections.append(f"({len(self.allowed_relationship_types)} types)")
        sections.append(", ".join(self.allowed_relationship_types[:30]))
        if len(self.allowed_relationship_types) > 30:
            sections.append(f"... và {len(self.allowed_relationship_types) - 30} types khác")
        
        # Allowed node types
        sections.append("\n【NODE TYPES ĐƯỢC PHÉP】")
        sections.append(", ".join(self.allowed_node_types))
        
        # Flags
        flags = []
        if self.create_name_nodes: flags.append("Tạo Name nodes cho biến thể tên")
        if self.create_event_nodes: flags.append("Tạo Event nodes")
        if self.create_location_nodes: flags.append("Tạo Location nodes")
        if self.create_organization_nodes: flags.append("Tạo Organization nodes")
        if self.extract_temporal: flags.append("Trích xuất thông tin thời gian (năm, tháng, ngày)")
        if self.extract_spatial: flags.append("Trích xuất thông tin không gian (địa điểm)")
        if self.extract_family: flags.append("Trích xuất quan hệ gia đình")
        if self.extract_social: flags.append("Trích xuất quan hệ chính trị/xã hội")
        
        if flags:
            sections.append("\n【TÍNH NĂNG】")
            for flag in flags:
                sections.append(f"✓ {flag}")
        
        # Priority target
        if self.priority_target:
            sections.append(f"\n⚠️ ƯU TIÊN: '{self.priority_target}' và người có quan hệ trực tiếp")
        
        # Custom instruction
        if self.custom_instruction:
            sections.append(f"\n【HƯỚNG DẪN THÊM】")
            sections.append(self.custom_instruction)
        
        return "\n".join(sections)


# ============================================================================
# DEFAULT CONFIG
# ============================================================================

DEFAULT_CONFIG = ExtractionConfig()


# ============================================================================
# ORIGINAL PROMPT - TẠO NHIỀU NODE VỚI CHIỀU SÂU (ENHANCED)
# ============================================================================

ORIGINAL_EXTRACTION_PROMPT = r"""Bạn là chuyên gia Knowledge Graph TUYỆT ĐỐI KHÔNG BỎ SÓT. Nhiệm vụ của bạn là trích xuất TẤT CẢ thông tin từ văn bản.

⚠️ NGUYÊN TẮC TUYỆT ĐỐI SỐ 1: KHÔNG BỎ SÓT BẤT KỲ DATA NÀO
- MỌI thông tin trong text phải được TRÍCH XUẤT
- Kể cả thông tin NHỎ NHẤT như: tên chữ Hán, tên đệm, tên lót, bí danh, số điện thoại, địa chỉ...
- Đặc biệt PHẢI TRÍCH XUẤT:
  • Tên chữ Hán (Hán tự): ví dụ "Bảo Đại" → "保大"
  • Các loại tên: khai sinh, tự, hiệu, tặng, tố, tước, thụy, miếu, đạo hiệu...
  • Năm sinh, năm mất, ngày sinh, ngày mất (nếu có)
  • Quê quán, nơi sinh, nơi mất (cụ thể đến làng/xã)
  • Họ hàng, dòng tộc, gia đình
  • Mọi chức vụ, chức danh đã từng giữ
  • Mọi sự kiện liên quan dù nhỏ
  • Mọi người dù liên quan đến targerperson ít

⚠️ NGUYÊN TẮC TUYỆT ĐỐI SỐ 2: XÁC ĐỊnh NGƯỜI NHẬN/NGƯỜI THỰC HIỆN
- VỚI MỌI HÀNH ĐỘNG phải xác định: AI LÀM, CHO AI, VỚI AI
- Ví dụ: "trao ấn kiếm cho Trần Huy Liệu" → TẠO NODE Trần Huy Liệu + RELATIONSHIP
- Ví dụ: "ông đã trao ấn tín và bảo kiếm" → TÌM XEM TRAO CHO AI → TẠO NODE + RELATIONSHIP GAVE_TO
- Ví dụ: "Hồ Chí Minh đọc tuyên ngôn" → TẠO NODE Hồ Chí Minh + EVENT + RELATIONSHIP
- Nếu text nói "trao/cấp/chuyển giao X cho/bởi Y" → PHẢI TÌM Y trong text
- KHÔNG BAO GIỜ bỏ qua người nhận/người thực hiện

⚠️ NGUYÊN TẮC SỐ 3: MỖI NODE PHẢI NHIỀU PROPERTIES
- MỖI node PHẢI CÓ ÍT NHẤT 8-15 properties chi tiết
- KHÔNG bao giờ tạo node chỉ có "name" + "description"
- Tự động SUY LUẬN thêm properties nếu thấy hợp lý

⚠️ NGUYÊN TẮC SỐ 3: MỌI NODE ĐỀU PHẢI KẾT NỐI
- MỖI node phải có ÍT NHẤT 2-4 relationships
- Không có node "treo lơ lửng" không kết nối

⚠️ NGUYÊN TẮC SỐ 4: VÍ DỤ CÁCH ĐỌC TEXT
- Text: "Bảo Đại (1913-1997), tên chữ Hán là 保大, tên khai sinh Nguyễn Phúc Vĩnh San, quê ở Huế..."
→ Phải tạo:
  • Node Person với: name, title, birth_year, death_year, han_name (保大), birth_place, dynasty, education, career, achievements, family...
  • Node Name cho: 保大 (han_name), Nguyễn Phúc Vĩnh San (khai_sinh), Bảo Đại (hieu)...
  • Node Location cho: Huế, Đại Nội Huế...
  • Node Event cho: đăng quang, thoái vị...

==============================================================
LOẠI 1: NGƯỜI (Person) - ĐẦY ĐỦ PROPERTIES
==============================================================
├── PROPERTIES BẮT BUỘC (ít nhất 10):
│   ├── name: Tên đầy đủ
│   ├── title: Danh hiệu/tước vị (Hoàng đế, Vua, Đại tướng, Giáo sư...)
│   ├── han_name: Tên chữ Hán (ví dụ: 保大, 阮惠...)
│   ├── birth_name: Tên khai sinh
│   ├── birth_year, death_year
│   ├── birth_month, birth_day, death_month, death_day (nếu có)
│   ├── birth_place, death_place
│   ├── dynasty: Triều đại
│   ├── role: Vai trò/chức vụ chính
│   └── description: Mô tả đầy đủ 2-3 câu
├── PROPERTIES BỔ SUNG (thêm từ text):
│   ├── reign_start, reign_end: Năm trị vì
│   ├── temple_name: Miếu hiệu
│   ├── posthumous_name: Thụy hiệu
│   ├── courtesy_name: Tự
│   ├── art_name: Hiệu
│   ├── childhood_name: Tên trẻ thơ
│   ├── pen_name: Bút danh
│   ├── education: Học vấn, trường học
│   ├── career: Sự nghiệp, chức vụ đã giữ
│   ├── personality: Tính cách nổi bật
│   ├── achievements: Thành tựu nổi bật
│   ├── family_background: Gia đình gốc
│   ├── notable_relationships: Quan hệ đáng chú ý
│   ├── quotes: Câu nói nổi tiếng
│   └── any_info: Mọi thông tin khác từ text
├── CÁC BIẾN THỂ TÊN - TẠO NODE RIÊNG:
│   ├── Tên chữ Hán → name_type: "han_name" + thuộc tính han_name
│   ├── Tên khai sinh → name_type: "khai_sinh"
│   ├── Tên tự → name_type: "tu"
│   ├── Tên hiệu → name_type: "hieu"
│   ├── Tên tặng → name_type: "tang"
│   ├── Tên tố → name_type: "to"
│   ├── Tước vị → name_type: "tuoc_vi"
│   ├── Thụy hiệu → name_type: "thuy_hieu"
│   ├── Miếu hiệu → name_type: "mieu_hieu"
│   ├── Bút danh → name_type: "but_danh"
│   └── Biệt danh → name_type: "biet_danh"
├── QUAN HỆ BẮT BUỘC (ít nhất 3-4):
│   ├── Cha/Mẹ → PARENT_OF / CHILD_OF
│   ├── Vợ/Chồng → SPOUSE_OF
│   ├── Con cái → PARENT_OF / CHILD_OF
│   ├── Anh chị em → SIBLING_OF
│   ├── Thầy → MENTOR_OF
│   ├── Trò → STUDENT_OF
│   ├── Chủ → SERVED_UNDER
│   ├── Người nhận đồ → GAVE_TO / RECEIVED_FROM
│   ├── Người trao đồ → RECEIVED_FROM / GAVE_TO
│   └── Kẻ thù/Đối thủ → ENEMY_OF
└── SỰ KIỆN ĐÃ THAM GIA: PARTICIPATED_IN

==============================================================
LOẠI 2: SỰ KIỆN (Event) - PROPERTIES BẮT BUỘC (ÍT NHẤT 8)
==============================================================
├── PROPERTIES BẮT BUỘC:
│   ├── name: Tên sự kiện đầy đủ
│   ├── type: Loại (chính trị, quân sự, ngoại giao, văn hóa, cá nhân)
│   ├── year, month, day
│   ├── location: Địa điểm
│   ├── description: Mô tả chi tiết
│   └── significance: Ý nghĩa lịch sử
├── PROPERTIES TÙY CHỌN:
│   ├── causes, participants, results
│   ├── duration, outcome, scale
│   ├── casualties, before, after
│   └── any_detail
├── LOẠI SỰ KIỆN:
│   ├── CORONATION, ABDICATION, REFORM, EXECUTION, EXILE
│   ├── BATTLE, VICTORY, DEFEAT, SIEGE, CAPTURE
│   ├── TREATY, STATE_VISIT, ALLIANCE, NEGOTIATION
│   └── CONSTRUCTION, CREATION, CONFERENCE
└── QUAN HỆ: PARTICIPATED_IN, OCCURRED_AT, OCCURRED_IN, CAUSED, LEAD_TO

==============================================================
LOẠI 3: TRIỀU ĐẠI/THỜI KỲ (Era/Dynasty)
==============================================================
├── PROPERTIES: name, start_year, end_year, capital, founder, last_ruler, num_rulers, description
└── QUAN HỆ: RULED_DURING, FOUNDED, CAPITAL_OF, OCCURRED_DURING

==============================================================
LOẠI 4: TỔ CHỨC (Organization)
==============================================================
├── PROPERTIES: name, type, founded_year, dissolved_year, founder, leader, purpose, description
└── QUAN HỆ: MEMBER_OF, LED_BY, FOUNDED_BY, PARTICIPATED_IN

==============================================================
LOẠI 5: ĐỊA ĐIỂM (Location)
==============================================================
├── PROPERTIES: name, type, country, region, historical_significance, description
└── QUAN HỆ: BORN_IN, DIED_AT, OCCURRED_IN, RULED, LOCATED_AT

==============================================================
VÍ DỤ MINH HỌA (RICH PROPERTIES - ĐẦY ĐỦ)
==============================================================

Input: "Bảo Đại (1913-1997), tên chữ Hán là 保大, tên khai sinh Nguyễn Phúc Vĩnh San, quê ở Huế, là vị Hoàng đế cuối cùng của Việt Nam thuộc Nhà Nguyễn. Ngày 30/8/1945, ông thoái vị tại Đại Nội Huế và trao ấn tín, bảo kiếm cho Trần Huy Liệu - Chủ tịch Ủy ban kháng chiến miền Nam Việt Nam. Ông là con trai của vua Khải Định. Vợ ông là Nam Phương hoàng hậu."

Output ĐÚNG (RICH - ĐẦY ĐỦ + NGƯỜI NHẬN):
```json
{{
  "nodes": [
    {{
      "id": "p1", 
      "type": "Person", 
      "name": "Bảo Đại",
      "properties": {{
        "title": "Hoàng đế cuối cùng Việt Nam",
        "role": "Hoàng đế nhà Nguyễn",
        "han_name": "保大",
        "birth_name": "Nguyễn Phúc Vĩnh San",
        "birth_year": 1913,
        "death_year": 1997,
        "birth_place": "Huế, Việt Nam",
        "death_place": "Paris, Pháp",
        "dynasty": "Nhà Nguyễn",
        "reign_start": 1926,
        "reign_end": 1945,
        "education": "Học tại Pháp",
        "career": "Hoàng đế (1926-1945), Đại sứ Việt Nam tại Pháp",
        "family_background": "Con trai vua Khải Định, chắt vua Minh Mạng",
        "achievements": "Hoàn thành việc chuyển giao quyền lực hòa bình",
        "description": "Vị hoàng đế cuối cùng của Việt Nam, trị vì từ 1926 đến 1945"
      }}
    }},
    {{
      "id": "p_thl", 
      "type": "Person", 
      "name": "Trần Huy Liệu",
      "properties": {{
        "title": "Chủ tịch Ủy ban kháng chiến miền Nam Việt Nam",
        "role": "Nhà cách mạng",
        "birth_year": 1903,
        "death_year": 1970,
        "birth_place": "Hà Nội, Việt Nam",
        "description": "Người được Bảo Đại trao ấn tín, bảo kiếm khi thoái vị năm 1945"
      }}
    }},
    {{
      "id": "n_han", 
      "type": "Name", 
      "name": "保大",
      "properties": {{
        "name_type": "han_name",
        "meaning": "Bảo = Giữ, Đại = Lớn",
        "pronunciation": "Bảo Đại"
      }}
    }},
    {{
      "id": "e_thv", 
      "type": "Event", 
      "name": "Bảo Đại thoái vị 1945",
      "properties": {{
        "type": "chính_trị",
        "year": 1945,
        "month": 8,
        "day": 30,
        "location": "Đại Nội Huế, Huế, Việt Nam",
        "description": "Bảo Đại chính thức thoái vị",
        "significance": "Chấm dứt chế độ quân chủ ở Việt Nam",
        "action": "trao ấn tín, bảo kiếm"
      }}
    }}
  ],
  "relationships": [
    {{"from": "p1", "type": "HAS_NAME", "to": "n_han", "properties": {{"name_type": "han_name"}}}},
    {{"from": "p1", "type": "CHILD_OF", "to": "p3"}},
    {{"from": "p1", "type": "SPOUSE_OF", "to": "p2"}},
    {{"from": "p1", "type": "PERFORMED", "to": "e_thv"}},
    {{"from": "e_thv", "type": "GAVE_TO", "to": "p_thl", "properties": {{"item": "ấn tín, bảo kiếm"}}}},
    {{"from": "p_thl", "type": "RECEIVED_FROM", "to": "p1", "properties": {{"item": "ấn tín, bảo kiếm"}}}}
  ]
}}
```

==============================================================
THỰC HÀNH - ĐOẠN VĂN CẦN PHÂN TÍCH
==============================================================

{text}

==============================================================
YÊU CẦU BẮT BUỘC - ĐỌC KỸ:
==============================================================
1. MỖI NODE PHẢI CÓ ÍT NHẤT 5-10 PROPERTIES chi tiết từ text
2. KHÔNG tạo node với chỉ name + description
3. TỰ DO THÊM properties bất kỳ từ text
4. MỖI NODE phải có ÍT NHẤT 2-3 RELATIONSHIPS
5. Tạo BIẾN THỂ TÊN cho MỌI người
6. Tạo node EVENT cho MỌI sự kiện có thông tin
7. Tạo node LOCATION cho MỌI địa điểm
8. TRÍCH XUẤT TỐI ĐA thông tin từ text
9. XÁC ĐỊNH NGƯỜI NHẬN/NGƯỜI THỰC HIỆN cho MỌI hành động
   - "trao X cho Y" → TẠO NODE Y + GAVE_TO
   - "nhận X từ Y" → TẠO NODE Y + RECEIVED_FROM
   - "làm gì với ai" → TÌM người đó trong text
{filter_instruction}

Output JSON (CHỈ JSON, KHÔNG text khác):
{
    "nodes": [...],
    "relationships": [...]
}
"""


# ============================================================================
# BASE PROMPT - NỀN TẢNG CHO PROMPT ĐỘNG
# ============================================================================

BASE_PROMPT_TEMPLATE = """Bạn là chuyên gia Knowledge Graph CHUYÊN SÂU. Phân tích đoạn văn và trích xuất nodes + relationships.

⚠️ NGUYÊN TẮC TUYỆT ĐỐI: KHÔNG BỎ SÓT THÔNG TIN
- MỌI người, sự kiện, địa điểm, tổ chức, khái niệm trong text → TẠO NODE
- TẠO NODE với TẤT CẢ thông tin có trong text (KHÔNG giới hạn properties)
- Tự do thêm properties BẤT KỲ khi thấy cần thiết từ text

==============================================================
CẤU HÌNH EXTRACTION
==============================================================
{config}

==============================================================
MỞ RỘNG PROPERTIES TỰ DO
==============================================================

Ngoài properties đã liệt kê, TỰ DO thêm bất kỳ properties nào từ text:
- Mọi thông tin về người: năm sinh/mất, quê quán, học vấn, sự nghiệp, tính cách...
- Mọi thông tin về sự kiện: thời gian, địa điểm, người tham gia, kết quả, ý nghĩa...
- Mọi thông tin về địa điểm: quốc gia, loại, ý nghĩa lịch sử...
- Mọi thông tin về tổ chức: năm thành lập, lãnh đạo, mục tiêu, thành tựu...
- Mọi thông tin khác: giải thưởng, danh hiệu, tác phẩm, phát minh...

==============================================================
ĐOẠN VĂN CẦN PHÂN TÍCH
==============================================================

{text}

==============================================================
YÊU CẦU BẮT BUỘC
==============================================================
1. MỌI thứ trong text → TẠO NODE với ĐẦY ĐỦ properties
2. Tự do thêm properties BẤT KỲ khi thấy thông tin trong text
3. TẠO TỐI ĐA relationships - kết nối mọi thứ liên quan
4. KHÔNG có node rỗng (phải có description hoặc mô tả tương đương)
5. Sử dụng relationship types từ danh sách được phép
6. {priority_instruction}

Output JSON (CHỈ JSON):
{{
    "nodes": [...],
    "relationships": [...]
}}
"""


def build_extraction_prompt(
    text: str,
    config: Optional["ExtractionConfig"] = None,
) -> str:
    """
    Build prompt từ config - linh hoạt, tùy chỉnh được.
    
    Args:
        text: Text cần phân tích
        config: Cấu hình extraction (None = dùng default)
    
    Returns:
        Prompt hoàn chỉnh
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    priority_instruction = ""
    if config.priority_target:
        priority_instruction = "Ưu tiên: '" + config.priority_target + "' và người có quan hệ trực tiếp với '" + config.priority_target + "'"
    else:
        priority_instruction = "Trích xuất TỐI ĐA thông tin, không bỏ sót gì"
    
    # Use replace instead of format to avoid JSON brace issues
    prompt = BASE_PROMPT_TEMPLATE.replace("{config}", config.to_prompt_section())
    prompt = prompt.replace("{text}", text)
    prompt = prompt.replace("{priority_instruction}", priority_instruction)
    return prompt


def build_original_prompt(
    text: str,
    target_person: Optional[str] = None,
) -> str:
    """
    Build ORIGINAL PROMPT - giữ nguyên logic cũ tạo NHIỀU node.
    
    Args:
        text: Text cần phân tích
        target_person: Người ưu tiên (None = trích xuất tất cả)
    
    Returns:
        Prompt hoàn chỉnh
    """
    filter_instruction = ""
    if target_person:
        filter_instruction = "⚠️ Ưu tiên: '" + target_person + "' và người có quan hệ trực tiếp. Tuy nhiên vẫn trích xuất TỐI ĐA những gì được nhắc đến."
    else:
        filter_instruction = "⚠️ TRÍCH XUẤT TỐI ĐA - không bỏ sót bất kỳ thông tin nào!"
    
    # Use replace instead of format to avoid JSON brace issues
    prompt = ORIGINAL_EXTRACTION_PROMPT.replace("{text}", text)
    prompt = prompt.replace("{filter_instruction}", filter_instruction)
    return prompt


# ============================================================================
# PRESET CONFIGS - CẤU HÌNH SẴN
# ============================================================================

PRESET_CONFIGS = {
    # Cấu hình mặc định - cân bằng
    "default": ExtractionConfig(),
    
    # Cấu hình cho lịch sử Việt Nam
    "vietnam_history": ExtractionConfig(
        priority_target="",
        extract_family=True,
        extract_social=True,
        custom_instruction="""- Ưu tiên trích xuất: năm sinh/mất, triều đại, chức vụ, tước vị
- Với vua/chúa: trích xuất tên thật, tên hiệu, thụy hiệu, miếu hiệu
- Với sự kiện: trích xuất ngày/tháng/năm chính xác, địa điểm, nhân vật
- Với tổ chức: trích xuất năm thành lập, người sáng lập, mục tiêu""",
        required_properties={
            "Person": {
                "name": "Tên đầy đủ",
                "title": "Danh hiệu/tước vị",
                "role": "Vai trò/chức vụ",
                "birth_year": "Năm sinh",
                "death_year": "Năm mất",
                "birth_place": "Nơi sinh",
                "description": "Mô tả ngắn (ai, làm gì, ý nghĩa)",
                "dynasty": "Triều đại (nếu có)",
                "achievements": "Thành tựu nổi bật",
                "notable_facts": "Sự kiện đáng chú ý",
            },
            "Event": {
                "name": "Tên sự kiện",
                "year": "Năm",
                "month": "Tháng",
                "day": "Ngày",
                "type": "Loại sự kiện",
                "location": "Địa điểm",
                "description": "Mô tả sự kiện",
                "significance": "Ý nghĩa lịch sử",
                "participants": "Người tham gia",
            },
            "Location": {
                "name": "Tên địa điểm",
                "type": "Loại (quốc gia, tỉnh, thành phố...)",
                "country": "Quốc gia",
                "description": "Mô tả",
                "historical_role": "Vai trò lịch sử",
            },
            "Organization": {
                "name": "Tên tổ chức",
                "full_name": "Tên đầy đủ",
                "type": "Loại (chính trị, quân sự...)",
                "founded_year": "Năm thành lập",
                "leader": "Người sáng lập/lãnh đạo",
                "description": "Mô tả",
            },
            "Dynasty": {
                "name": "Tên triều đại",
                "start_year": "Năm bắt đầu",
                "end_year": "Năm kết thúc",
                "description": "Mô tả",
            },
        },
    ),
    
    # Cấu hình cho khoa học/công nghệ
    "science_tech": ExtractionConfig(
        extract_family=False,
        extract_social=True,
        custom_instruction="""- Ưu tiên trích xuất: lĩnh vực nghiên cứu, phát minh/sáng chế, giải thưởng
- Với nhà khoa học: trích xuất năm sinh/mất, trường đại học, lĩnh vực, học trò
- Với phát minh: trích xuất năm, người phát minh, ý nghĩa, ứng dụng
- Với giải thưởng: trích xuất tên giải thưởng, năm, người nhận""",
        required_properties={
            "Person": {
                "name": "Tên nhà khoa học",
                "birth_year": "Năm sinh",
                "death_year": "Năm mất",
                "field": "Lĩnh vực nghiên cứu",
                "institution": "Tổ chức/trường",
                "description": "Mô tả",
                "awards": "Giải thưởng",
                "inventions": "Phát minh/sáng chế",
            },
            "Concept": {
                "name": "Tên khái niệm/lý thuyết",
                "field": "Lĩnh vực",
                "description": "Mô tả",
                "discovered_by": "Người phát hiện",
                "year_discovered": "Năm phát hiện",
            },
            "Work": {
                "name": "Tên công trình/tác phẩm",
                "type": "Loại",
                "author": "Tác giả",
                "year": "Năm",
                "description": "Mô tả",
            },
        },
    ),
    
    # Cấu hình cho văn học/nghệ thuật
    "literature_art": ExtractionConfig(
        extract_family=True,
        extract_social=True,
        custom_instruction="""- Ưu tiên trích xuất: tác phẩm, thể loại, giải thưởng, trường phái
- Với tác giả: trích xuất năm sinh/mất, tác phẩm chính, phong cách
- Với tác phẩm: trích xuất năm xuất bản, thể loại, tác giả, nhân vật chính
- Với nghệ sĩ: trích xuất thể loại, tác phẩm tiêu biểu, trường phái""",
        required_properties={
            "Person": {
                "name": "Tên tác giả/nghệ sĩ",
                "birth_year": "Năm sinh",
                "death_year": "Năm mất",
                "genre": "Thể loại",
                "style": "Phong cách",
                "description": "Mô tả",
                "major_works": "Tác phẩm chính",
                "awards": "Giải thưởng",
            },
            "Work": {
                "name": "Tên tác phẩm",
                "type": "Loại (văn học, hội họa, âm nhạc...)",
                "author": "Tác giả",
                "year": "Năm sáng tác/xuất bản",
                "description": "Mô tả",
                "genre": "Thể loại",
                "significance": "Ý nghĩa",
            },
        },
    ),
    
    # Cấu hình tối thiểu - chỉ lấy thông tin cơ bản
    "minimal": ExtractionConfig(
        create_name_nodes=False,
        create_event_nodes=True,
        create_location_nodes=True,
        create_organization_nodes=True,
        extract_temporal=True,
        extract_spatial=True,
        extract_family=True,
        extract_social=True,
        custom_instruction="Chỉ trích xuất thông tin CƠ BẢN nhất, không thêm quá nhiều chi tiết",
        required_properties={
            "Person": {
                "name": "Tên",
                "description": "Mô tả ngắn",
            },
            "Event": {
                "name": "Tên sự kiện",
                "description": "Mô tả",
            },
        },
    ),
    
    # Cấu hình tối đa - lấy mọi thứ có thể
    "maximum": ExtractionConfig(
        custom_instruction="""TRÍCH XUẤT TỐI ĐA:
- Mọi thông tin về mọi người: tên, tuổi, nghề nghiệp, tính cách, sở thích, câu nói nổi tiếng...
- Mọi thông tin về mọi sự kiện: chi tiết, phụ lục, hậu quả, nhân chứng...
- Mọi thông tin về mọi địa điểm: lịch sử, dân số, đặc điểm...
- Mọi mối quan hệ có thể có
- Mọi thông tin bổ sung: ngày tháng, con số, so sánh...""",
    ),
}


def get_preset_config(name: str) -> ExtractionConfig:
    """Lấy preset config theo tên."""
    return PRESET_CONFIGS.get(name, DEFAULT_CONFIG)


def create_custom_config(**kwargs) -> ExtractionConfig:
    """Tạo config tùy chỉnh từ kwargs."""
    return ExtractionConfig(**kwargs)


# ============================================================================
# MAIN EXTRACTOR CLASS
# ============================================================================

class CustomGraphExtractor:
    """Extract nodes + relationships với extraction linh hoạt."""

    def __init__(
        self, 
        graph_db: Optional[GraphDB] = None, 
        model: Optional[str] = None,
        config: Optional[ExtractionConfig] = None,
    ):
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)
        self.model = model or os.getenv("YESCALE_MODEL", "gemini-2.0-flash")
        self.config = config or DEFAULT_CONFIG
        
        api_key = os.getenv("YESCALE_API_KEY")
        if not api_key:
            raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong env.")

    def set_config(self, config: ExtractionConfig):
        """Thay đổi config."""
        self.config = config
    
    def set_preset(self, preset_name: str):
        """Đặt preset config."""
        self.config = get_preset_config(preset_name)
    
    def update_config(self, **kwargs):
        """Cập nhật config hiện tại."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def extract_from_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        target_person: Optional[str] = None,
        config: Optional[ExtractionConfig] = None,
        use_original_prompt: bool = True,
    ) -> Dict[str, Any]:
        """
        Extract nodes và relationships với config linh hoạt.
        
        Args:
            text: Text cần phân tích
            source_chunk_id: ID của chunk nguồn
            target_person: Ưu tiên người này
            config: Cấu hình extraction (None = dùng config của instance)
            use_original_prompt: True = dùng prompt gốc (nhiều node), False = dùng config-based prompt
        
        Returns:
            dict với "nodes" và "relationships"
        """
        use_config = config or self.config
        
        # Override priority_target nếu có target_person
        if target_person:
            use_config.priority_target = target_person
        
        # Build prompt
        if use_original_prompt:
            # Dùng ORIGINAL PROMPT - tạo NHIỀU node nhất có thể
            prompt = build_original_prompt(text, target_person)
        else:
            # Dùng CONFIG-BASED PROMPT - linh hoạt theo config
            prompt = build_extraction_prompt(text, use_config)

        try:
            print(f"[DEBUG] Calling LLM for extraction...")
            print(f"[DEBUG] Using {'ORIGINAL' if use_original_prompt else 'CONFIG'} prompt mode")
            response = call_llm(prompt, model=self.model, temperature=use_config.temperature)
            
            # Parse JSON
            data = json.loads(response)
            
        except json.JSONDecodeError:
            try:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    print(f"⚠️ Failed to parse LLM response as JSON")
                    return {"nodes": [], "relationships": []}
            except Exception as e:
                print(f"⚠️ Error parsing LLM response: {e}")
                return {"nodes": [], "relationships": []}

        # Validate và enrich
        data = self._validate_and_fix_relationships(data, text)
        data = self._enrich_properties_from_text(data, text)

        print(f"[DEBUG] Extracted: {len(data.get('nodes', []))} nodes, {len(data.get('relationships', []))} relationships")
        
        return data

    def _enrich_properties_from_text(self, data: Dict[str, Any], text: str) -> Dict[str, Any]:
        """Post-process: Enrich missing properties từ text gốc (rule-based)."""
        nodes = data.get("nodes", [])
        
        year_pattern = r'(\d{4})(?:-(\d{4}))?'
        birth_pattern = r'(?:sinh|năm sinh)[:\s]*(\d{4})'
        death_pattern = r'(?:mất|năm mất|qua đời)[:\s]*(\d{4})'
        
        for node in nodes:
            if node.get("type") != "Person":
                continue
                
            props = node.get("properties", {})
            name = node.get("name", "")
            
            if not props.get("birth_year"):
                match = re.search(birth_pattern, text)
                if match:
                    props["birth_year"] = int(match.group(1))
            
            if not props.get("death_year"):
                match = re.search(death_pattern, text)
                if match:
                    props["death_year"] = int(match.group(1))
            
            location_keywords = ["ở", "tại", "quê", "quê quán"]
            for keyword in location_keywords:
                pattern = rf'{keyword}\s+([^,\.]+?)(?:,|\.|$)'
                match = re.search(pattern, text)
                if match and not props.get("birth_place"):
                    place = match.group(1).strip()
                    if 2 < len(place) < 50:
                        props["birth_place"] = place
            
            org_keywords = ["thuộc", "đảng", "viện", "hội", "quân đội"]
            for keyword in org_keywords:
                pattern = rf'{re.escape(name)}[^\.]*{keyword}\s+([^,\.]+?)(?:,|\.|$)'
                match = re.search(pattern, text)
                if match and not props.get("organization"):
                    org = match.group(1).strip()
                    if 2 < len(org) < 50:
                        props["organization"] = org
                        break
            
            node["properties"] = props
        
        data["nodes"] = nodes
        return data

    def _validate_and_fix_relationships(
        self, 
        data: Dict[str, Any], 
        text: str = ""
    ) -> Dict[str, Any]:
        """Validate và fix orphan nodes."""
        nodes = data.get("nodes", [])
        relationships = data.get("relationships", [])
        
        connected_ids = set()
        for rel in relationships:
            if rel.get("from"):
                connected_ids.add(rel["from"])
            if rel.get("to"):
                connected_ids.add(rel["to"])
        
        orphan_nodes = []
        for node in nodes:
            node_id = node.get("id")
            if node_id and node_id not in connected_ids:
                orphan_nodes.append(node)
        
        if orphan_nodes:
            print(f"[DEBUG] Found {len(orphan_nodes)} orphan nodes, trying to fix...")
            for orphan in orphan_nodes:
                self._fix_orphan_node(orphan, nodes, relationships, text)
        
        data["nodes"] = nodes
        data["relationships"] = relationships
        return data

    def _fix_orphan_node(
        self, 
        orphan: Dict, 
        all_nodes: List[Dict], 
        relationships: List[Dict],
        text: str = ""
    ) -> bool:
        """Fix orphan node."""
        orphan_id = orphan.get("id")
        orphan_type = orphan.get("type")
        orphan_name = orphan.get("name", "")
        
        if orphan_type == "Name":
            for node in all_nodes:
                if node.get("type") == "Person":
                    person_name = node.get("name", "")
                    if any(word in orphan_name for word in person_name.split() if len(word) > 3):
                        relationships.append({
                            "from": node.get("id"),
                            "type": "HAS_NAME",
                            "to": orphan_id,
                            "properties": orphan.get("properties", {})
                        })
                        return True
        
        if orphan_type == "Event":
            for node in all_nodes:
                if node.get("type") == "Person":
                    person_name = node.get("name", "")
                    if person_name and person_name in orphan_name:
                        relationships.append({
                            "from": node.get("id"),
                            "type": "PERFORMED",
                            "to": orphan_id,
                            "properties": {}
                        })
                        return True
        
        if orphan_type == "Location":
            for node in all_nodes:
                if node.get("type") in ["Person", "Event"]:
                    node_name = node.get("name", "")
                    if node_name and node_name in orphan_name:
                        rel_type = "BORN_IN" if node.get("type") == "Person" else "LOCATED_AT"
                        relationships.append({
                            "from": node.get("id"),
                            "type": rel_type,
                            "to": orphan_id,
                            "properties": {}
                        })
                        return True
        
        if orphan_type == "Organization":
            for node in all_nodes:
                if node.get("type") == "Person":
                    props = node.get("properties", {})
                    if props.get("organization") == orphan_name:
                        relationships.append({
                            "from": node.get("id"),
                            "type": "MEMBER_OF",
                            "to": orphan_id,
                            "properties": {}
                        })
                        return True
        
        return False

    def build_from_extraction(self, extracted_data: Dict[str, Any]) -> Tuple[int, int]:
        """Build graph từ extracted data."""
        nodes = []
        rels = []
        node_lookup = {}

        for node in extracted_data.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type", "Unknown")
            node_name = node.get("name", "")
            node_props = node.get("properties", {})

            # Normalize reign properties for Person nodes
            if node_type == "Person":
                node_props = self._normalize_reign_properties(node_props)
                node["properties"] = node_props

            if node_id:
                node_lookup[node_id] = node
            if node_name:
                node_lookup[node_name] = node

            if node_type == "Name":
                identifier = {"value": node_name}
            else:
                identifier = {"name": node_name}

            nodes.append({
                "type": node_type,
                "identifier": identifier,
                "properties": node_props
            })

        # Ensure dynasty metadata and relationships exist for Person nodes
        dynasty_nodes = {n["identifier"]["name"] for n in nodes if n["type"] == "Dynasty"}

        def _relation_key(value: Any) -> Any:
            if isinstance(value, dict):
                return tuple(sorted(value.items()))
            return str(value)

        existing_rel_pairs = set(
            (
                _relation_key(rel.get("from")),
                _relation_key(rel.get("to")),
                rel.get("type")
            )
            for rel in extracted_data.get("relationships", [])
        )

        for node in extracted_data.get("nodes", []):
            if node.get("type") != "Person":
                continue
            props = node.get("properties", {})
            dynasty_name = props.get("dynasty")
            if dynasty_name:
                dynasty_node_id = f"dynasty:{dynasty_name}"
                if dynasty_name not in dynasty_nodes:
                    nodes.append({
                        "id": dynasty_node_id,
                        "type": "Dynasty",
                        "identifier": {"name": dynasty_name},
                        "properties": {"name": dynasty_name}
                    })
                    dynasty_nodes.add(dynasty_name)
                    node_lookup[dynasty_node_id] = {
                        "id": dynasty_node_id,
                        "type": "Dynasty",
                        "name": dynasty_name,
                        "properties": {"name": dynasty_name}
                    }

                person_key = node.get("id") or node.get("name", "")
                rel_key = (
                    _relation_key(person_key),
                    _relation_key(dynasty_node_id),
                    "BELONGS_TO_DYNASTY"
                )
                if rel_key not in existing_rel_pairs:
                    extracted_data.get("relationships", []).append({
                        "from": node.get("id") or node.get("name", ""),
                        "type": "BELONGS_TO_DYNASTY",
                        "to": dynasty_node_id,
                        "properties": {}
                    })
                    existing_rel_pairs.add(rel_key)

        for rel in extracted_data.get("relationships", []):
            from_id = rel.get("from")
            to_id = rel.get("to")
            rel_type = rel.get("type", "RELATED_TO")

            from_node = node_lookup.get(from_id, {})
            to_node = node_lookup.get(to_id, {})

            from_type = from_node.get("type", "Unknown")
            to_type = to_node.get("type", "Unknown")
            from_name = from_node.get("name", from_id)
            to_name = to_node.get("name", to_id)

            if from_type == "Name":
                from_id_dict = {"value": from_name}
            else:
                from_id_dict = {"name": from_name}

            if to_type == "Name":
                to_id_dict = {"value": to_name}
            else:
                to_id_dict = {"name": to_name}

            rels.append({
                "from_type": from_type,
                "from_id": from_id_dict,
                "rel_type": rel_type,
                "to_type": to_type,
                "to_id": to_id_dict,
                "properties": rel.get("properties", {}),
            })

        # Legacy support
        for person in extracted_data.get("persons", []):
            person_name = person.get("name")
            if not person_name:
                continue

            person_props = {
                "role": person.get("role"),
                "birth_year": person.get("birth_year"),
                "death_year": person.get("death_year"),
                "description": person.get("description", ""),
            }
            person_props = self._normalize_reign_properties(person_props)

            nodes.append({
                "type": "Person",
                "identifier": {"name": person_name},
                "properties": person_props
            })

        if nodes or rels:
            result = self.builder.batch_create_nodes(nodes)
            if isinstance(result, dict):
                nodes_created = result.get("nodes_created", 0)
            else:
                nodes_created = result if result else len(nodes)
            
            relationships_created = 0
            for rel in rels:
                try:
                    self.builder.create_relationship(
                        rel["from_type"],
                        rel["from_id"],
                        rel["rel_type"],
                        rel["to_type"],
                        rel["to_id"],
                        rel_properties=rel.get("properties", {})
                    )
                    relationships_created += 1
                except Exception:
                    pass

        else:
            nodes_created = 0
            relationships_created = 0

        return nodes_created, relationships_created

    def _normalize_reign_properties(self, props: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize and compute reign metadata from extracted person properties."""
        if not isinstance(props, dict):
            return props

        if props.get("reign_start") and not props.get("reign_start_year"):
            try:
                props["reign_start_year"] = int(props["reign_start"])
            except Exception:
                pass

        if props.get("reign_end") and not props.get("reign_end_year"):
            try:
                props["reign_end_year"] = int(props["reign_end"])
            except Exception:
                pass

        start_year = props.get("reign_start_year")
        end_year = props.get("reign_end_year")
        if start_year is not None and end_year is not None:
            try:
                props["reign_duration_years"] = abs(int(end_year) - int(start_year))
            except Exception:
                pass

        return props

    def enrich_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        link_to_person: Optional[str] = None,
        use_original_prompt: bool = True,
    ) -> Tuple[int, int]:
        """
        Enrich text: extract và build graph.
        
        Args:
            text: Text cần phân tích
            source_chunk_id: ID của chunk nguồn
            link_to_person: Người ưu tiên
            use_original_prompt: True = dùng prompt gốc (nhiều node), False = dùng config-based prompt
        
        Returns:
            (nodes_created, relationships_created)
        """
        extracted = self.extract_from_text(
            text, 
            source_chunk_id, 
            target_person=link_to_person,
            use_original_prompt=use_original_prompt,
        )
        nodes_created, rels_created = self.build_from_extraction(extracted)
        
        return nodes_created, rels_created

    def enrich_from_wikichunks(self, limit: int = 100) -> Dict[str, int]:
        """Enrich from WikiChunk nodes in Neo4j."""
        with self.graph_db.driver.session(database=self.graph_db.database) as session:
            result = session.run(
                """
                MATCH (w:WikiChunk)
                WHERE w.content IS NOT NULL
                RETURN coalesce(w.chunk_id, toString(w.id)) AS cid, w.content AS content
                LIMIT $limit
                """,
                limit=limit,
            )
            chunks = [(r["cid"], r["content"]) for r in result]

        total_nodes = 0
        total_rels = 0
        for cid, content in chunks:
            try:
                n, r = self.enrich_text(content, source_chunk_id=cid)
                total_nodes += n
                total_rels += r
                print(f"  Chunk {cid}: {n} nodes, {r} rels")
            except Exception as e:
                print(f"  Error chunk {cid}: {e}")

        return {"nodes_created": total_nodes, "relationships_created": total_rels}


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def extract_with_preset(
    text: str, 
    preset: str = "default",
    target_person: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Extract với preset config - tiện lợi cho sử dụng nhanh.
    
    Args:
        text: Text cần phân tích
        preset: Tên preset ("default", "vietnam_history", "science_tech", "literature_art", "minimal", "maximum")
        target_person: Ưu tiên người này
        **kwargs: Override config
    
    Returns:
        Extracted data
    
    Examples:
        # Dùng preset sẵn
        data = extract_with_preset(text, "vietnam_history")
        
        # Dùng preset với override
        data = extract_with_preset(text, "vietnam_history", custom_instruction="Thêm thông tin về...")
        
        # Dùng config tùy chỉnh hoàn toàn
        config = ExtractionConfig(
            priority_target="Hồ Chí Minh",
            custom_instruction="Ưu tiên thông tin cách mạng",
            required_properties={...}
        )
        data = extract_with_preset(text, preset="default", config=config)
    """
    config = get_preset_config(preset)
    
    # Override với kwargs
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    
    if target_person:
        config.priority_target = target_person
    
    extractor = CustomGraphExtractor(config=config)
    return extractor.extract_from_text(text, target_person=target_person)


# ============================================================================
# USAGE EXAMPLES (uncomment to test)
# ============================================================================

if __name__ == "__main__":
    # Ví dụ 1: Dùng preset sẵn
    print("=" * 50)
    print("Ví dụ 1: Preset Vietnam History")
    print("=" * 50)
    config = get_preset_config("vietnam_history")
    print(config.to_prompt_section())
    
    # Ví dụ 2: Tạo config tùy chỉnh
    print("\n" + "=" * 50)
    print("Ví dụ 2: Config tùy chỉnh")
    print("=" * 50)
    custom_config = ExtractionConfig(
        priority_target="Hồ Chí Minh",
        custom_instruction="Chỉ trích xuất thông tin về hoạt động cách mạng",
        temperature=0.1,
    )
    print(custom_config.to_prompt_section())
    
    # Ví dụ 3: Update config hiện tại
    print("\n" + "=" * 50)
    print("Ví dụ 3: Update config")
    print("=" * 50)
    extractor = CustomGraphExtractor()
    extractor.update_config(
        priority_target="Trần Hưng Đạo",
        custom_instruction="Thêm thông tin về chiến trận",
    )
    print("Config updated!")
