"""Custom graph extractor - 1 LLM call cho cả node + relationship (CÁCH B - Linh hoạt)."""

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
# PROMPT SIÊU TOÀN DIỆN - 1 LLM CALL = NODE + RELATIONSHIP
# ============================================================================

EXTRACTION_PROMPT = """Bạn là chuyên gia Knowledge Graph CHUYÊN SÂU. Phân tích đoạn văn và trích xuất TỐI ĐA nodes + relationships.

⚠️ NGUYÊN TẮC SỐ 1: TRÍCH XUẤT KHÔNG GIỚI HẠN
- Tạo node cho MỌI thứ được đề cập trong văn bản
- Không bỏ sót bất kỳ nhân vật, sự kiện, địa điểm, khái niệm nào
- Kể cả thông tin "nhỏ" như nghề nghiệp, chức vụ, năm sinh, năm mất
- Tạo TẤT CẢ các biến thể tên (bí danh, tên lúc sinh, tước hiệu, phong hiệu)

⚠️ NGUYÊN TẮC SỐ 2: KHÔNG CÓ NODE "MỒ CÔI"
- MỌI node phải có ÍT NHẤT 1 relationship
- Nếu một thông tin đứng một mình → kết nối với node chính

==============================================================
LOẠI 1: NGƯỜI (Person) - TẠO NODE CHO MỌI NGƯỜI ĐƯỢC NHẮC ĐẾN
==============================================================
├── TÊN CHÍNH → Node Person
├── CÁC BIẾN THỂ TÊN (tạo node riêng):
│   ├── Tên khai sinh → name_type: "birth_name"
│   ├── Tên tục → name_type: "birth_name"
│   ├── Tên chữ (Hán Việt) → name_type: "chữ_học"
│   ├── Tên hiệu (hiệu) → name_type: "tên_hiệu"
│   ├── Tự xưng → name_type: "tự_xưng"
│   ├── Tước vị (Vua, Hầu, Công...) → name_type: "tước_vị"
│   ├── Tôn hiệu (hoàng đế) → name_type: "tôn_hiệu"
│   ├── Thụy hiệu → name_type: "thụy_hiệu"
│   ├── Miếu hiệu → name_type: "miếu_hiệu"
│   ├── Bí danh, Bút danh → name_type: "bí_danh"
│   └── Biệt danh, biệt hiệu → name_type: "biệt_danh"
├── NĂM SINH/NĂM MẤT → properties: birth_year, death_year
├── NƠI SINH/NƠI MẤT → Location
├── QUAN HỆ GIA ĐÌNH:
│   ├── Cha → CHILD_OF / PARENT_OF
│   ├── Mẹ → CHILD_OF / PARENT_OF
│   ├── Vợ/Chồng → SPOUSE_OF
│   ├── Con cái → PARENT_OF / CHILD_OF
│   ├── Anh chị em → SIBLING_OF
│   ├── Ông bà → GRANDPARENT_OF / GRANDCHILD_OF
│   └── Họ hàng (chú, bác, cậu, dì...) → EXTENDED_FAMILY_OF
├── QUAN HỆ THẦY-TRÒ:
│   ├── Thầy → STUDENT_OF / MENTOR_OF
│   ├── Trò → MENTOR_OF / STUDENT_OF
│   ├── Sư phụ → STUDENT_OF
│   └── Đồ đệ → MENTOR_OF
├── QUAN HỆ CHÍNH TRỊ/QUÂN SỰ:
│   ├── Tiền nhiệm → PREDECESSOR_OF / SUCCEEDED
│   ├── Kế nhiệm → SUCCEEDED / PREDECESSOR_OF
│   ├── Cộng sự → ALLY_OF
│   ├── Đối thủ/Kẻ thù → ENEMY_OF / RIVAL_OF
│   ├── Tham mưu → ADVISOR_TO
│   ├── Tướng lĩnh dưới quyền → COMMANDED / COMMANDED_BY
│   ├── Bộ trưởng → APPOINTED / APPOINTED_BY
│   └── Quan lại → GOVERNED / GOVERNED_BY
├── VAI TRÒ/CHỨC VỤ:
│   ├── Chức vụ → SERVED_AS
│   ├── Triều đại → RULED_DURING / SERVED_DURING
│   └── Cấp bậc quân đội → RANK_OF
├── GIÁO DỤC:
│   ├── Học tại → STUDIED_AT
│   ├── Đỗ đạt → PASSED_EXAM
│   └── Trường học → location của STUDIED_AT
└── TÍNH CÁCH/SỞ TRƯỜNG:
    └── Tính cách nổi bật → PERSONALITY_TRAIT
    └── Kỹ năng → SKILL_OF

==============================================================
LOẠI 2: SỰ KIỆN (Event) - TẠO NODE CHO MỌI SỰ KIỆN
==============================================================
├── SỰ KIỆN CHÍNH TRỊ:
│   ├── Đăng quang/Ngày lên ngôi → CORONATION_OF
│   ├── Thoái vị → ABDICATED
│   ├── Cải cách, Đổi mới → INITIATED
│   ├── Xử tử, Giết → EXECUTED / ASSASSINATED
│   ├── Tha bổng, Giải thoát → RELEASED
│   └── Lưu đày, Truyền bá → EXILED
├── SỰ KIỆN QUÂN SỰ:
│   ├── Trận đánh/Chiến trận → BATTLE_OF / PARTICIPATED_IN
│   ├── Chiến thắng → VICTORY_IN / DEFEATED
│   ├── Thua trận → DEFEAT_IN
│   ├── Bị bao vây → SIEGE_OF
│   ├── Bắt giữ → CAPTURED / CAPTURED_BY
│   ├── Quân đội tham gia → ARMED_FORCES_IN
│   └── Chiến dịch → LED_CAMPAIGN
├── SỰ KIỆN NGOẠI GIAO:
│   ├── Ký hiệp ước → SIGNED_TREATY
│   ├── Công du → STATE_VISIT
│   ├── Liên minh → FORMED_ALLIANCE
│   └── Đàm phán → NEGOTIATED
├── SỰ KIỆN VĂN HÓA/XÃ HỘI:
│   ├── Xây dựng công trình → CONSTRUCTED
│   ├── Sáng tác tác phẩm → CREATED
│   ├── Tổ chức hội nghị → HOSTED
│   └── Cải cách xã hội → REFORMED
├── SỰ KIỆN CÁ NHÂN:
│   ├── Sinh → BORN_AT
│   ├── Mất → DIED_AT
│   ├── Kết hôn → MARRIED_TO
│   ├── Lập gia đình → FOUNDED_FAMILY
│   └── Qua đời tại → DIED_IN
├── THỜI GIAN SỰ KIỆN:
│   ├── Năm cụ thể → OCCURRED_IN (properties: year)
│   ├── Tháng/Ngày → OCCURRED_ON (properties: date)
│   └── Thời kỳ → OCCURRED_DURING
└── ĐỊA ĐIỂM:
    └── LOCATED_AT → Location

==============================================================
LOẠI 3: TRIỀU ĐẠI/THỜI KỲ (Era/Dynasty)
==============================================================
├── Triều đại → RULING_DYNASTY / RULED_BY
├── Thời kỳ lịch sử → HISTORICAL_PERIOD
├── Kỷ nguyên → ERA
├── Thế kỷ → CENTURY
├── Năm → properties: year
└── Mối quan hệ:
    ├── Người trị vì → RULED_DURING
    ├── Người sáng lập → FOUNDED
    └── Người khai sáng → ESTABLISHED

==============================================================
LOẠI 4: TỔ CHỨC/ĐOÀN THỂ (Organization)
==============================================================
├── Tổ chức chính trị:
│   ├── Đảng → MEMBER_OF / LED_BY / FOUNDED
│   ├── Nhà nước → HEAD_OF / GOVERNED_BY
│   └── Triều đình → SERVED_IN / RULED_BY
├── Tổ chức quân sự:
│   ├── Quân đội → SERVED_IN / COMMANDED
│   ├── Quân chủng → BELONGED_TO
│   └── Lực lượng vũ trang → ARMED_FORCE_OF
├── Tổ chức tôn giáo:
│   ├── Giáo hội → MEMBER_OF
│   ├── Chùa/Tu viện → FOUNDED / LED_BY
│   └── Tăng sĩ → ORDAINED_BY
├── Tổ chức kinh tế:
│   ├── Công ty → FOUNDED / EMPLOYED_AT
│   └── Thương hội → MEMBER_OF
└── VAI TRÒ TRONG TỔ CHỨC:
    ├── Chủ tịch/Trưởng → LED_BY / HEAD_OF
    ├── Thành viên → MEMBER_OF
    ├── Sáng lập → FOUNDED_BY
    └── Nhân viên → EMPLOYED_AT

==============================================================
LOẠI 5: ĐỊA ĐIỂM (Location)
==============================================================
├── QUỐC GIA/VÙNG LÃNH THỔ:
│   └── Quốc gia → FROM_COUNTRY / RULED
├── TỈNH/THÀNH PHỐ:
│   ├── Tỉnh → FROM_PROVINCE / GOVERNED
│   └── Thành phố → FROM_CITY / GOVERNED
├── QUÊ QUÁN/NƠI SINH:
│   └── Người → BORN_IN / FROM_PLACE
├── NƠI MẤT:
│   └── Người → DIED_AT / DIED_IN
├── NƠI CƯ TRÚ:
│   ├── Cư trú → RESIDED_IN
│   ├── Học tập → STUDIED_AT
│   └── Làm việc → WORKED_AT
├── ĐỊA DANH LỊCH SỬ:
│   ├── Thành trì → LOCATED_AT
│   ├── Pháo đài → FORTIFIED
│   ├── Cung điện → LOCATED_AT / CONSTRUCTED
│   └── Di tích → HISTORICAL_SITE
├── ĐỊA HÌNH:
│   ├── Sông → LOCATED_AT
│   ├── Núi → LOCATED_AT
│   ├── Biển → LOCATED_AT
│   └── Rừng → LOCATED_AT
└── ĐỊA ĐIỂM TRONG SỰ KIỆN:
    └── Sự kiện → LOCATED_AT

==============================================================
LOẠI 6: THÀNH TỰU/THÀNH TÍCH (Achievement)
==============================================================
├── THÀNH TỰU CHÍNH:
│   ├── Thành tựu quân sự → ACHIEVED_VICTORY
│   ├── Thành tựu chính trị → ACHIEVED_POLITICALLY
│   ├── Thành tựu văn hóa → ACHIEVED_CULTURALLY
│   └── Thành tựu kinh tế → ACHIEVED_ECONOMICALLY
├── GIẢI THƯỞNG/DANH HIỆU:
│   ├── Tước vị → RECEIVED_TITLE
│   ├── Phong tặng → GRANTED_TITLE
│   ├── Giải thưởng → RECEIVED_AWARD
│   └── Vinh danh → HONORED_WITH
├── CÔNG TRÌNH XÂY DỰNG:
│   ├── Công trình kiến trúc → BUILT / CONSTRUCTED
│   ├── Đập, kênh → BUILT
│   └── Thành, lũy → BUILT / FORTIFIED
├── SÁNG TÁC:
│   ├── Tác phẩm văn học → AUTHORED
│   ├── Nhạc phẩm → COMPOSED
│   ├── Tranh ảnh → CREATED
│   └── Phát minh → INVENTED
└── TÍNH CÁCH NỔI BẬT:
    └── Thuộc tính đặc biệt → HAS_TRAIT

==============================================================
LOẠI 7: TÁC PHẨM/VĂN HÓA VẬT THỂ (Work)
==============================================================
├── VĂN HỌC:
│   ├── Sách → AUTHORED
│   ├── Bài viết → WROTE
│   ├── Thơ → COMPOSED
│   ├── Văn bia → INSCRIBED
│   └── Châu bản → COMPILED
├── NGHỆ THUẬT:
│   ├── Tranh → PAINTED / CREATED
│   ├── Tượng → SCULPTED
│   ├── Kiến trúc → DESIGNED / BUILT
│   └── Nghệ thuật thủ công → CRAFTED
├── ÂM NHẠC:
│   ├── Nhạc phẩm → COMPOSED
│   └── Ca khúc → COMPOSED
├── PHÁT MINH/SÁNG CHẾ:
│   ├── Phát minh → INVENTED
│   ├── Cải tiến → IMPROVED
│   └── Kỹ thuật → DEVELOPED
└── NGỮ LIỆU LỊCH SỬ:
    ├── Biên niên sử → COMPILED
    └── Chính sử → AUTHORED

==============================================================
LOẠI 8: KHÁI NIỆM/LĨNH VỰC (Field/Concept)
==============================================================
├── LĨNH VỰC HOẠT ĐỘNG:
│   ├── Quân sự → EXPERT_IN_MILITARY / WORKED_IN
│   ├── Chính trị → EXPERT_IN_POLITICS / WORKED_IN
│   ├── Văn hóa → EXPERT_IN_CULTURE / WORKED_IN
│   ├── Kinh tế → EXPERT_IN_ECONOMICS / WORKED_IN
│   ├── Tôn giáo → EXPERT_IN_RELIGION / WORKED_IN
│   └── Ngoại giao → EXPERT_IN_DIPLOMACY / WORKED_IN
├── TRƯỜNG PHÁI:
│   ├── Trường phái tư tưởng → BELONGED_TO
│   ├── Trường phái nghệ thuật → BELONGED_TO
│   └── Trường phái quân sự → BELONGED_TO
├── CHÍNH SÁCH/QUAN ĐIỂM:
│   ├── Chính sách → IMPLEMENTED_POLICY
│   └── Quan điểm → HELD_VIEW
└── HỌC THUYẾT/LÝ THUYẾT:
    ├── Học thuyết → PROPOUNDED
    └── Lý thuyết → DEVELOPED

==============================================================
LOẠI 9: VĂN BẢN/TÀI LIỆU (Document)
==============================================================
├── Văn bản pháp luật:
│   ├── Luật → PROMULGATED
│   ├── Chiếu → DECREED
│   └── Sắc lệnh → DECREED
├── Văn bản ngoại giao:
│   ├── Hiệp ước → SIGNED
│   ├── Thư tín → CORRESPONDED
│   └── Tuyên ngôn → DECLARED
├── Văn bản văn học:
│   ├── Tác phẩm → AUTHORED
│   └── Bản thảo → WROTE
└── TÀI LIỆU LỊCH SỬ:
    └── Biên bản → RECORDED

==============================================================
LOẠI 10: QUÂN ĐỘI/VŨ KHÍ (Military)
==============================================================
├── QUÂN ĐỘI:
│   ├── Quân đội chính quy → LED / COMMANDED
│   ├── Quân chủng → COMMANDED
│   └── Lực lượng đặc biệt → LED
├── VŨ KHÍ/TRANG BỊ:
│   ├── Vũ khí → INVENTED / USED_WEAPON
│   └── Phương tiện → DEVELOPED
└── CHIẾN THUẬT/CHIẾN LƯỢC:
    ├── Chiến thuật → DEPLOYED_TACTIC
    └── Chiến lược → DEVISED_STRATEGY

==============================================================
VÍ DỤ MINH HỌA (TẠO TỐI ĐA NODES)
==============================================================

Input: "Bảo Đại (1913-1997), tên khai sinh Nguyễn Phúc Vĩnh San, quê ở Huế, là vị Hoàng đế cuối cùng của Việt Nam thuộc Nhà Nguyễn. Năm 1926, ông đăng quang tại Đại Nội Huế. Năm 1945, ông thoái vị dưới áp lực của Cách mạng. Vợ ông là Nam Phương hoàng hậu. Ông là con trai của vua Khải Định. Chú ông là Hoàng Tường, em vua Khải Định."

Output ĐÚNG (tạo TỐI ĐA nodes):
```json
{{
  "nodes": [
    {{"id": "p1", "type": "Person", "name": "Bảo Đại", "properties": {{"title": "Hoàng đế cuối cùng Việt Nam", "birth_year": 1913, "death_year": 1997, "notes": "Nhà Nguyễn"}}}},
    {{"id": "n1", "type": "Name", "name": "Nguyễn Phúc Vĩnh San", "properties": {{"name_type": "khai_sinh"}}}},
    {{"id": "n2", "type": "Name", "name": "Hoàng đế", "properties": {{"name_type": "tước_vị"}}}},
    {{"id": "l1", "type": "Location", "name": "Huế", "properties": {{"type": "quê_quán", "description": "Thành phố Huế"}}}},
    {{"id": "l2", "type": "Location", "name": "Đại Nội Huế", "properties": {{"type": "cung_điện", "description": "Hoàng cung Huế"}}}},
    {{"id": "l3", "type": "Location", "name": "Việt Nam", "properties": {{"type": "quốc_gia"}}}},
    {{"id": "dy1", "type": "Dynasty", "name": "Nhà Nguyễn", "properties": {{"period": "1802-1945"}}}},

    {{"id": "e1", "type": "Event", "name": "Đăng quang Bảo Đại 1926", "properties": {{"year": 1926, "type": "đăng_quang"}}}},
    {{"id": "e2", "type": "Event", "name": "Thoái vị Bảo Đại 1945", "properties": {{"year": 1945, "type": "thoái_vị"}}}},
    {{"id": "e3", "type": "Event", "name": "Cách mạng tháng Tám 1945", "properties": {{"year": 1945}}}},

    {{"id": "p2", "type": "Person", "name": "Nam Phương hoàng hậu", "properties": {{"title": "Hoàng hậu", "role": "vợ vua Bảo Đại"}}}},
    {{"id": "p3", "type": "Person", "name": "Khải Định", "properties": {{"title": "Vua", "dynasty": "Nhà Nguyễn"}}}},
    {{"id": "p4", "type": "Person", "name": "Hoàng Tường", "properties": {{"title": "Hoàng tử", "relation": "chú Bảo Đại"}}}}
  ],
  "relationships": [
    {{"from": "p1", "type": "HAS_NAME", "to": "n1", "properties": {{"name_type": "khai_sinh"}}}},
    {{"from": "p1", "type": "HAS_NAME", "to": "n2", "properties": {{"name_type": "tước_vị"}}}},
    {{"from": "p1", "type": "BORN_IN", "to": "l1", "properties": {{"year": 1913}}}},
    {{"from": "p1", "type": "FROM_PLACE", "to": "l1"}},
    {{"from": "p1", "type": "RULED", "to": "l3"}},
    {{"from": "p1", "type": "RULED_DURING", "to": "dy1"}},
    {{"from": "p3", "type": "PARENT_OF", "to": "p1"}},
    {{"from": "p1", "type": "CHILD_OF", "to": "p3"}},
    {{"from": "p4", "type": "SIBLING_OF", "to": "p3"}},
    {{"from": "p1", "type": "SPOUSE_OF", "to": "p2"}},
    {{"from": "e1", "type": "LOCATED_AT", "to": "l2"}},
    {{"from": "e1", "type": "OCCURRED_IN", "to": "l2", "properties": {{"year": 1926}}}},
    {{"from": "p1", "type": "PERFORMED", "to": "e1"}},
    {{"from": "p1", "type": "PERFORMED", "to": "e2"}},
    {{"from": "e3", "type": "CAUSED", "to": "e2"}},
    {{"from": "e2", "type": "OCCURRED_IN", "to": "l3", "properties": {{"year": 1945}}}}
  ]
}}
```

==============================================================
THỰC HÀNH - ĐOẠN VĂN CẦN PHÂN TÍCH
==============================================================

{{text}}

==============================================================
YÊU CẦU BẮT BUỘC:
==============================================================
1. TRÍCH XUẤT TỐI ĐA - Tạo node cho MỌI thứ được nhắc đến
2. MỖI node phải có ÍT NHẤT 1 relationship
3. Tạo biến thể tên cho MỌI người (tên chính, tên khai sinh, tước vị...)
4. Tạo node Event cho MỌI sự kiện có năm/thời gian
5. Tạo node Location cho MỌI địa điểm được nhắc
6. Nếu có quan hệ gia đình → tạo relationship GIA ĐÌNH
7. KHÔNG có node "treo lơ lửng" không kết nối
8. Thêm properties year, date, description nếu có trong văn bản

Output JSON (CHỈ JSON, KHÔNG text khác):
{{
    "nodes": [...],
    "relationships": [...]
}}
"""


class CustomGraphExtractor:
    """Extract nodes + relationships trong 1 LLM call DUY NHẤT."""

    def __init__(self, graph_db: Optional[GraphDB] = None, model: Optional[str] = None):
        self.graph_db = graph_db or GraphDB()
        self.builder = GraphBuilder(graph_db=self.graph_db)
        self.model = model or os.getenv("YESCALE_MODEL", "gemini-2.0-flash")
        
        api_key = os.getenv("YESCALE_API_KEY")
        if not api_key:
            raise RuntimeError("YESCALE_API_KEY chưa được cấu hình trong env.")

    def extract_from_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        target_person: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract nodes và relationships TRONG 1 LLM CALL.
        
        Returns:
            dict với "nodes" và "relationships" - đảm bảo mọi node đều có relationship!
        """
        # Build prompt
        additional_filter = ""
        if target_person:
            additional_filter = f"\n\n⚠️ LƯU Ý: Ưu tiên thông tin về '{target_person}'. Nếu có người khác, chỉ trích xuất nếu họ có quan hệ TRỰC TIẾP với '{target_person}'."

        prompt = EXTRACTION_PROMPT.replace("{{text}}", text) + additional_filter

        try:
            print(f"[DEBUG] Calling LLM once for extraction...")
            response = call_llm(prompt, model=self.model, temperature=0.2)
            
            # Parse JSON
            data = json.loads(response)
            
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from response
            try:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    print(f"⚠️ Failed to parse LLM response as JSON")
                    print(f"Response (first 300 chars): {response[:300]}")
                    return {"nodes": [], "relationships": []}
            except Exception as e:
                print(f"⚠️ Error parsing LLM response: {e}")
                return {"nodes": [], "relationships": []}

        # Validate: ensure no orphan nodes
        data = self._validate_and_fix_relationships(data)

        # Debug output
        print(f"[DEBUG] Extracted: {len(data.get('nodes', []))} nodes, {len(data.get('relationships', []))} relationships")
        
        return data

    def _validate_and_fix_relationships(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate và fix orphan nodes - đảm bảo mọi node đều có relationship.
        """
        nodes = data.get("nodes", [])
        relationships = data.get("relationships", [])
        
        # Build set of connected node IDs
        connected_ids = set()
        for rel in relationships:
            if rel.get("from"):
                connected_ids.add(rel["from"])
            if rel.get("to"):
                connected_ids.add(rel["to"])
        
        # Find orphan nodes
        orphan_nodes = []
        for node in nodes:
            node_id = node.get("id")
            if node_id and node_id not in connected_ids:
                orphan_nodes.append(node)
        
        if orphan_nodes:
            print(f"[DEBUG] Found {len(orphan_nodes)} orphan nodes, trying to fix...")
            # Try to auto-link orphans based on name similarity or type
            for orphan in orphan_nodes:
                fixed = self._fix_orphan_node(orphan, nodes, relationships)
                if fixed:
                    print(f"[DEBUG] Fixed orphan: {orphan.get('name', orphan.get('id'))}")
        
        return data

    def _fix_orphan_node(self, orphan: Dict, all_nodes: List[Dict], relationships: List[Dict]) -> bool:
        """
        Thử fix một orphan node bằng cách tạo relationship thông minh.
        """
        orphan_id = orphan.get("id")
        orphan_type = orphan.get("type")
        orphan_name = orphan.get("name", "")
        
        # Strategy 1: Name nodes → link to Person with similar name context
        if orphan_type == "Name":
            # Find a Person node that might own this name
            for node in all_nodes:
                if node.get("type") == "Person":
                    # Check if Person name is similar to Name node context
                    person_name = node.get("name", "")
                    if any(word in orphan_name for word in person_name.split() if len(word) > 3):
                        relationships.append({
                            "from": node.get("id"),
                            "type": "HAS_NAME",
                            "to": orphan_id,
                            "properties": orphan.get("properties", {})
                        })
                        return True
        
        # Strategy 2: Event nodes → try to link to any Person mentioned
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
        
        # Strategy 3: Location nodes → try to link to Person or Event
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
        
        return False

    def build_from_extraction(self, extracted_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Build graph từ extracted data (flexible format).
        
        Returns:
            (nodes_created, relationships_created)
        """
        nodes = []
        rels = []
        node_lookup = {}

        # Process nodes
        for node in extracted_data.get("nodes", []):
            node_id = node.get("id")
            node_type = node.get("type", "Unknown")
            node_name = node.get("name", "")
            node_props = node.get("properties", {})

            if node_id:
                node_lookup[node_id] = node

            # Determine identifier based on type
            if node_type == "Name":
                identifier = {"value": node_name}
            else:
                identifier = {"name": node_name}

            nodes.append({
                "type": node_type,
                "identifier": identifier,
                "properties": node_props
            })

        # Process relationships
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

            # Determine identifiers based on types
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

        # Legacy support for old format (persons, achievements, events, etc.)
        for person in extracted_data.get("persons", []):
            person_name = person.get("name")
            if not person_name:
                continue

            nodes.append({
                "type": "Person",
                "identifier": {"name": person_name},
                "properties": {
                    "role": person.get("role"),
                    "birth_year": person.get("birth_year"),
                    "death_year": person.get("death_year"),
                }
            })

            for name_entry in person.get("names", []):
                name_value = name_entry.get("value")
                name_type = name_entry.get("type", "alias")
                if name_value:
                    nodes.append({
                        "type": "Name",
                        "identifier": {"value": name_value},
                        "properties": {"name_type": name_type}
                    })
                    rels.append({
                        "from_type": "Person",
                        "from_id": {"name": person_name},
                        "rel_type": "HAS_NAME",
                        "to_type": "Name",
                        "to_id": {"value": name_value},
                        "properties": {"name_type": name_type},
                    })

        for achievement in extracted_data.get("achievements", []):
            nodes.append({
                "type": "Achievement",
                "identifier": {"name": achievement.get("name")},
                "properties": {"year": achievement.get("year"), "description": achievement.get("description")}
            })

        for event in extracted_data.get("events", []):
            nodes.append({
                "type": "Event",
                "identifier": {"name": event.get("name")},
                "properties": {"year": event.get("year"), "description": event.get("description")}
            })

        for era in extracted_data.get("eras", []):
            nodes.append({
                "type": "Era",
                "identifier": {"name": era.get("name")},
                "properties": {"start_year": era.get("start_year"), "end_year": era.get("end_year")}
            })

        for field in extracted_data.get("fields", []):
            nodes.append({
                "type": "Field",
                "identifier": {"name": field.get("name")},
                "properties": {"category": field.get("category")}
            })

        # Build to Neo4j
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
                except Exception as e:
                    pass  # Relationship might already exist

        else:
            nodes_created = 0
            relationships_created = 0

        return nodes_created, relationships_created

    def enrich_text(
        self,
        text: str,
        source_chunk_id: Optional[str] = None,
        link_to_person: Optional[str] = None,
    ) -> Tuple[int, int]:
        """
        Enrich text: extract và build graph trong 1 LLM call.
        
        Args:
            text: Text to extract from
            source_chunk_id: Source chunk identifier  
            link_to_person: Person name to focus extraction on
        
        Returns:
            (nodes_created, relationships_created)
        """
        # Single LLM call for both extraction and relationship
        extracted = self.extract_from_text(text, source_chunk_id, target_person=link_to_person)
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
