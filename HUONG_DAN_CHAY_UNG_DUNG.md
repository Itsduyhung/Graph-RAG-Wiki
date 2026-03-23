# 🚀 Hướng Dẫn Chạy Ứng Dụng Trên Trình Duyệt

Hướng dẫn từng bước để chạy Graph RAG Agent trên trình duyệt web.

---

## 📋 Yêu Cầu Hệ Thống

Trước khi bắt đầu, đảm bảo bạn đã cài đặt:

- ✅ **Python 3.8+** (kiểm tra: `python --version`)
- ✅ **Neo4j Database** (đang chạy)
- ✅ **Ollama** (đang chạy với model đã pull)

---

## 🔧 Bước 1: Cài Đặt Dependencies

Mở Terminal/PowerShell và chạy:

```bash
# Di chuyển vào thư mục project
cd D:\Agent-Demo

# Tạo virtual environment (nếu chưa có)
python -m venv venv

# Kích hoạt virtual environment
# Trên Windows PowerShell:
.\venv\Scripts\Activate.ps1

# Trên Windows CMD:
.\venv\Scripts\activate.bat

# Trên Linux/Mac:
source venv/bin/activate

# Cài đặt các packages cần thiết
pip install -r requirements.txt
```

**Kiểm tra cài đặt:**
```bash
pip list
# Bạn sẽ thấy: neo4j, streamlit, requests, python-dotenv, ...
```

---

## ⚙️ Bước 2: Cấu Hình Environment Variables

### 2.1. Tạo file secrets.env

```bash
# Copy template
copy config\secrets.env.template config\secrets.env
```

Hoặc tạo file `config/secrets.env` thủ công với nội dung:

```env
# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_DB=neo4j

# Ollama Configuration
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=mistral
```

### 2.2. Điền thông tin thực tế

**Thay đổi các giá trị sau:**

- `NEO4J_PASSWORD`: Mật khẩu Neo4j của bạn
- `NEO4J_URI`: Nếu Neo4j chạy ở port khác, thay đổi port
- `OLLAMA_MODEL`: Model bạn muốn dùng (mistral, llama2, phi, ...)

**Ví dụ:**
```env
NEO4J_PASSWORD=MyPassword123
OLLAMA_MODEL=llama2
```

---

## 🗄️ Bước 3: Khởi Động Neo4j

### Cách 1: Neo4j Desktop (Khuyến nghị)

1. Mở **Neo4j Desktop**
2. Start database của bạn
3. Đảm bảo database đang chạy (status: Running)
4. Copy **Bolt URI** và **Password** vào `config/secrets.env`

### Cách 2: Neo4j Community Edition

```bash
# Nếu cài đặt qua Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest

# Kiểm tra Neo4j đang chạy
# Mở trình duyệt: http://localhost:7474
```

### Kiểm tra kết nối:

```bash
python test_neo4j.py
# Hoặc
python test_env.py
```

Nếu thấy output với thông tin Neo4j → ✅ Kết nối thành công!

---

## 🤖 Bước 4: Khởi Động Ollama

### 4.1. Cài đặt Ollama (nếu chưa có)

Tải từ: https://ollama.ai/download

### 4.2. Khởi động Ollama Server

Mở Terminal/PowerShell mới và chạy:

```bash
# Khởi động Ollama server
ollama serve
```

**Lưu ý:** Giữ terminal này mở trong suốt quá trình sử dụng!

### 4.3. Pull Model

Mở Terminal/PowerShell khác và chạy:

```bash
# Pull model mistral (hoặc model bạn muốn dùng)
ollama pull mistral

# Hoặc các model khác:
# ollama pull llama2
# ollama pull phi
# ollama pull codellama
```

**Kiểm tra model đã được pull:**
```bash
ollama list
# Bạn sẽ thấy danh sách các models đã cài đặt
```

### 4.4. Test Ollama

```bash
# Test xem Ollama có hoạt động không
curl http://localhost:11434/api/generate -d '{
  "model": "mistral",
  "prompt": "Hello"
}'
```

Hoặc test bằng Python:
```python
from llm.llm_client import call_llm
response = call_llm("Hello, how are you?")
print(response)
```

---

## 📊 Bước 5: Chuẩn Bị Dữ Liệu (Tùy chọn)

Nếu bạn đã có dữ liệu trong Neo4j, có thể bỏ qua bước này.

Nếu chưa có dữ liệu, bạn có thể:

### Cách 1: Tạo dữ liệu mẫu bằng code

Tạo file `create_sample_data.py`:

```python
from graph.builder import GraphBuilder

builder = GraphBuilder()

# Tạo nodes
builder.create_node("Person", "John Doe", {"age": 35, "expertise": "AI"})
builder.create_node("Company", "Fintech X", {"industry": "Finance", "founded_year": 2020})
builder.create_node("Person", "Jane Smith", {"age": 30})

# Tạo relationships
builder.create_relationship("Person", "John Doe", "FOUNDED", "Company", "Fintech X", {"year": 2020})
builder.create_relationship("Person", "Jane Smith", "WORKS_AT", "Company", "Fintech X", {"role": "CTO"})

print("✅ Sample data created!")
```

Chạy:
```bash
python create_sample_data.py
```

### Cách 2: Ingest từ file JSON

Tạo file `data/raw/companies.json`:

```json
[
  {
    "type": "Person",
    "identifier": "John Doe",
    "properties": {"age": 35}
  },
  {
    "type": "Company",
    "identifier": "Fintech X",
    "properties": {"industry": "Finance"}
  },
  {
    "from_type": "Person",
    "from_id": "John Doe",
    "rel_type": "FOUNDED",
    "to_type": "Company",
    "to_id": "Fintech X",
    "properties": {"year": 2020}
  }
]
```

Chạy:
```python
from pipeline.ingest import DataIngestionPipeline

ingest = DataIngestionPipeline()
result = ingest.ingest_from_file("data/raw/companies.json", "json")
print(result)
```

---

## 🌐 Bước 6: Chạy Ứng Dụng Trên Trình Duyệt

### 6.1. Khởi động Streamlit

Trong Terminal/PowerShell (đã activate venv), chạy:

```bash
streamlit run api/app.py
```

Hoặc sử dụng file tương thích ngược:

```bash
streamlit run ui.py
```

### 6.2. Mở Trình Duyệt

Sau khi chạy lệnh trên, bạn sẽ thấy output như:

```
You can now view your Streamlit app in your browser.

Local URL: http://localhost:8501
Network URL: http://192.168.x.x:8501
```

**Mở trình duyệt và truy cập:** http://localhost:8501

### 6.3. Giao Diện Ứng Dụng

Bạn sẽ thấy:

```
🤖 Graph RAG AI Agent

[Chat input box: "Hỏi về doanh nghiệp..."]
```

---

## 💬 Bước 7: Sử Dụng Ứng Dụng

### 7.1. Đặt Câu Hỏi

Nhập câu hỏi vào ô chat, ví dụ:

- ✅ "Ai là người sáng lập của Fintech X?"
- ✅ "Fintech X được thành lập bởi ai?"
- ✅ "John Doe thành lập công ty nào?"

### 7.2. Xem Kết Quả

Ứng dụng sẽ:

1. Phân tích câu hỏi (extract intent)
2. Tìm kiếm trong Neo4j graph
3. Tạo câu trả lời bằng Ollama LLM
4. Hiển thị kết quả

### 7.3. Lịch Sử Chat

Tất cả câu hỏi và câu trả lời được lưu trong session và hiển thị trên màn hình.

---

## 🔍 Kiểm Tra và Xử Lý Lỗi

### Lỗi: "Không thể kết nối đến Neo4j"

**Nguyên nhân:**
- Neo4j chưa được khởi động
- Sai thông tin kết nối trong `config/secrets.env`

**Giải pháp:**
```bash
# Kiểm tra Neo4j đang chạy
# Mở: http://localhost:7474

# Kiểm tra lại config/secrets.env
# Đảm bảo NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD đúng
```

### Lỗi: "Không thể kết nối đến Ollama"

**Nguyên nhân:**
- Ollama server chưa được khởi động
- Model chưa được pull

**Giải pháp:**
```bash
# Terminal 1: Khởi động Ollama
ollama serve

# Terminal 2: Pull model
ollama pull mistral

# Kiểm tra
ollama list
```

### Lỗi: "ModuleNotFoundError"

**Nguyên nhân:**
- Chưa cài đặt dependencies
- Virtual environment chưa được activate

**Giải pháp:**
```bash
# Activate venv
.\venv\Scripts\Activate.ps1

# Cài đặt lại
pip install -r requirements.txt
```

### Lỗi: "Không tìm thấy dữ liệu"

**Nguyên nhân:**
- Neo4j chưa có dữ liệu
- Tên công ty/người không khớp với dữ liệu trong graph

**Giải pháp:**
- Tạo dữ liệu mẫu (xem Bước 5)
- Kiểm tra dữ liệu trong Neo4j Browser: http://localhost:7474
- Query: `MATCH (n) RETURN n LIMIT 25`

---

## 📝 Checklist Trước Khi Chạy

Trước khi chạy ứng dụng, đảm bảo:

- [ ] Python 3.8+ đã cài đặt
- [ ] Virtual environment đã được tạo và activate
- [ ] Dependencies đã được cài đặt (`pip install -r requirements.txt`)
- [ ] File `config/secrets.env` đã được tạo và điền đúng thông tin
- [ ] Neo4j đang chạy và có thể kết nối
- [ ] Ollama server đang chạy (`ollama serve`)
- [ ] Model đã được pull (`ollama pull mistral`)
- [ ] Dữ liệu đã được nạp vào Neo4j (hoặc sẽ tạo mẫu)

---

## 🎯 Quick Start (Tóm Tắt Nhanh)

```bash
# 1. Setup
cd D:\Agent-Demo
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Config
copy config\secrets.env.template config\secrets.env
# Edit config/secrets.env với thông tin thực tế

# 3. Start Neo4j (trong Neo4j Desktop hoặc Docker)

# 4. Start Ollama (Terminal mới)
ollama serve
# Terminal khác:
ollama pull mistral

# 5. Create sample data (nếu chưa có)
python create_sample_data.py

# 6. Run app
streamlit run api/app.py

# 7. Open browser
# http://localhost:8501
```

---

## 🛑 Dừng Ứng Dụng

### Dừng Streamlit:
- Nhấn `Ctrl + C` trong terminal đang chạy Streamlit

### Dừng Ollama:
- Nhấn `Ctrl + C` trong terminal đang chạy `ollama serve`

### Dừng Neo4j:
- Trong Neo4j Desktop: Click "Stop"
- Hoặc nếu dùng Docker: `docker stop neo4j`

---

## 💡 Tips và Tricks

### 1. Chạy trên Port Khác

```bash
streamlit run api/app.py --server.port 8502
```

### 2. Chạy với Model Khác

Sửa `config/secrets.env`:
```env
OLLAMA_MODEL=llama2
```

### 3. Xem Logs Chi Tiết

Streamlit tự động hiển thị logs trong terminal. Nếu có lỗi, kiểm tra terminal output.

### 4. Reset Session

Refresh trình duyệt (F5) để reset session state.

### 5. Kiểm Tra Dữ Liệu Trong Neo4j

Mở Neo4j Browser: http://localhost:7474

Query để xem tất cả nodes:
```cypher
MATCH (n) RETURN n LIMIT 25
```

Query để xem relationships:
```cypher
MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 25
```

---

## 📞 Hỗ Trợ

Nếu gặp vấn đề:

1. Kiểm tra lại các bước trong checklist
2. Xem logs trong terminal để biết lỗi cụ thể
3. Kiểm tra `ARCHITECTURE.md` để hiểu cách hệ thống hoạt động
4. Xem `SEQUENCE_DIAGRAMS.md` để hiểu luồng xử lý

---

**Chúc bạn sử dụng thành công! 🎉**
