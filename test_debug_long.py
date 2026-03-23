import requests
import json

# Longer, richer text
text = """
Kim Đồng là một vị vua trẻ tuổi nhất của Việt Nam, người lãnh đạo khởi nghĩa Tây Sơn. 
Ông đã tham gia khởi nghĩa Tây Sơn cùng với anh em và Quang Trung. 
Thành tựu chính của ông bao gồm:
- Thành lập quân đội lực lượng Tây Sơn mạnh mẽ
- Cải cách hệ thống chính trị với các luật lệ mới
- Xây dựng đất nước độc lập khỏi chiếm đóng
- Phát triển kinh tế nông nghiệp

Ông là học trò của Trần Hưng Đạo qua truyền thống chiến tranh du kích. 
Kim Đồng có mối quan hệ học trò với Nguyễn Ánh sau này.

Sự kiện lịch sử:
- Khởi nghĩa Tây Sơn (1778) chống lại nhà Nguyễn
- Chiến dịch Tây Sơn chống quân Thanh
- Đánh bại quân Thanh và tuyên bố độc lập
- Khởi nghĩa giải phóng dân tộc khỏi sự chiếm đóng

Lĩnh vực hoạt động:
- Quân sự: Chiến tranh, quân sự chiến lược
- Chính trị: Cải cách chính trị, quản lý nhà nước
- Lãnh đạo: Lãnh đạo quân đội, quản lý dân sự

Thời kỳ lịch sử:
- Thời kỳ Tây Sơn (1778-1802)
- Thế kỷ 18 ở Việt Nam
- Giai đoạn chống chiếm đóng nước ngoài

Quan hệ với các nhân vật:
- Quang Trung là đồng minh quan trọng
- Nguyễn Ánh là kẻ thù chính trị
- Trần Hưng Đạo là thầy giáo tinh thần
- Các anh em ruột trong quân Tây Sơn
"""

r = requests.post(
    'http://localhost:8000/debug-extract',
    params={
        'target_person': 'Kim Đồng',
        'text': text
    },
    timeout=30
)

result = r.json()
print("=" * 70)
print("EXTRACTION RESULTS")
print("=" * 70)

print(f"\n📊 Extracted Data Summary:")
print(f"  Persons: {len(result['extracted_data']['persons'])}")
print(f"  Achievements: {len(result['extracted_data']['achievements'])}")
print(f"  Events: {len(result['extracted_data']['events'])}")
print(f"  Eras: {len(result['extracted_data']['eras'])}")
print(f"  Fields: {len(result['extracted_data']['fields'])}")

print(f"\n✓ Nodes created: {result['nodes_created']}")
print(f"✓ Relationships created: {result['relationships_created']}")

print(f"\n📋 Achievements:")
for a in result['extracted_data']['achievements']:
    print(f"   • {a['name']}")

print(f"\n📋 Events:")
for e in result['extracted_data']['events']:
    print(f"   • {e['name']} ({e['event_type']})")

print(f"\n📋 Eras:")
for er in result['extracted_data']['eras']:
    print(f"   • {er['name']}")

print(f"\n📋 Fields:")
for f in result['extracted_data']['fields']:
    print(f"   • {f['name']}")

print("\n" + "=" * 70)
