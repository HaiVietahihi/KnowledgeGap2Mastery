# Báo Cáo Phân Tích Chi Tiết Chức Năng Hệ Thống KG2M

**Thời gian lập báo cáo:** 16/04/2026
**Phiên bản hệ thống:** Demo v1.0
**Mục đích tài liệu:** Phân tích toàn diện kiến trúc, luồng chức năng và các kỹ thuật triển khai của nền tảng KG2M (*Knowledge Gaps to Learning Opportunities*).

---

## 1. Tổng Quan Hệ Thống

#### 1.1. Mục Tiêu & Bối Cảnh

KG2M là nền tảng học tập thích ứng, vận hành theo hai vòng lặp chính:

1. **Phát hiện tự động:** Phân tích câu hỏi của sinh viên để nhận diện các vùng kiến thức mà nhóm học viên đang thiếu hụt (*Knowledge Gaps*).
2. **Sinh nội dung có mục tiêu:** Tự động tạo các cơ hội học tập phù hợp (*Learning Opportunities — LOP*) để làm rõ và lấp đầy các lỗ hổng đó.

#### 1.2. Ngăn Xếp Công Nghệ

| Thành phần | Công nghệ |
|---|---|
| Web Framework | Flask (Python) |
| Cơ sở dữ liệu | SQLite + SQLAlchemy ORM |
| Mô hình ngôn ngữ | LLM tự host qua Ollama API (mặc định: `gemma4:26b`) |
| Xử lý PDF | PageIndex (thư viện nội bộ) + PyPDF2 (fallback) |
| Giao diện | Jinja2 Templates + HTML/CSS |

#### 1.3. Hai Nhóm Người Dùng

Hệ thống phân chia rõ ràng hai vai trò:
- **Giảng viên (`instructor`):** Quản lý nội dung, kích hoạt pipeline AI, duyệt kết quả và theo dõi tiến độ lớp học.
- **Sinh viên (`student`):** Tham gia khóa học, đặt câu hỏi, làm bài tập và theo dõi tiến trình cá nhân.

---

## 2. Sơ Đồ Kiến Trúc Module

```
app.py (Application Factory)
│
├── routes/auth.py          → Đăng nhập / Đăng ký / Đăng xuất
├── routes/courses.py       → Quản lý khóa học (Giảng viên + Sinh viên)
├── routes/discovery.py     → Pipeline phát hiện lỗ hổng kiến thức
├── routes/refinement.py    → Duyệt & chỉnh sửa kết quả AI (Giảng viên)
├── routes/generation.py    → Sinh & quản lý Learning Opportunities
├── routes/analytics.py     → Dashboard thống kê & phân tích (Giảng viên)
└── routes/api.py           → JSON API polling (polling trạng thái task)
│
├── core/ingestion.py       → Xử lý PDF & RAG Engine
├── core/discovery.py       → AI Pipeline phát hiện lỗ hổng
├── core/generation.py      → AI Pipeline sinh LOP (CoT + Self-Refine)
└── core/utils.py           → LLM API client (Ollama, retry, throttle)
│
├── database/models.py      → SQLAlchemy Data Models
├── database/repository.py  → Repository Pattern (Data Access Layer)
└── database/db.py          → Khởi tạo & seed dữ liệu demo
│
└── services.py             → Singleton Services + Background Task Manager
```

---

## 3. Chi Tiết Chức Năng Theo Module

---

### 3.1. Module Xác thực (Authentication) — `routes/auth.py`

Module này là cổng vào duy nhất của hệ thống, quản lý danh tính người dùng thông qua Flask Session.

#### Chức năng:

| Endpoint | Phương thức | Mô tả |
|---|---|---|
| `GET /login` | GET | Hiển thị trang đăng nhập |
| `POST /login` | POST | Xác thực email + password (hash SHA-256) |
| `GET /register` | GET | Hiển thị form đăng ký tài khoản mới |
| `POST /register` | POST | Tạo tài khoản với vai trò `student` hoặc `instructor` |
| `GET /logout` | GET | Xóa session, chuyển về trang đăng nhập |

#### Cơ chế hoạt động:
- **Middleware tự động:** Trong `app.py`, hook `@app.before_request` được cài đặt để đọc `user_id` từ session rồi gán đối tượng `User` vào biến `g.current_user` trước mỗi request. Mọi blueprint đều có thể đọc `g.current_user` mà không cần truy vấn DB lại.
- **Mật khẩu:** Lưu trữ dưới dạng SHA-256 hash, không bao giờ lưu plaintext.

---

### 3.2. Module Quản Lý Khóa Học — `routes/courses.py`

Là trung tâm điều hướng cho cả giảng viên lẫn sinh viên. Mỗi endpoint đều kiểm tra vai trò người dùng (`role`) trước khi cho phép thực hiện.

#### 3.2.1. Chức Năng Dành Cho Giảng Viên

| Endpoint | Mô tả |
|---|---|
| `GET /courses/create` | Hiển thị form tạo khóa học mới |
| `POST /courses/create` | Tạo khóa học với tên, mã số và mô tả; tự sinh UUID cho `course_id` |
| `GET /courses/<id>` | Trang chi tiết khóa học: danh sách tài liệu, câu hỏi sinh viên, bài tập |
| `GET /courses/<id>/upload` | Hiển thị form upload tài liệu PDF |
| `POST /courses/<id>/upload` | Nhận file PDF, lưu vào thư mục `uploads/`, kích hoạt pipeline xử lý không đồng bộ |
| `POST /courses/<id>/document/<doc_id>/delete` | Xóa tài liệu khỏi DB và xóa file vật lý trên đĩa |

#### 3.2.2. Chức Năng Dành Cho Sinh Viên

| Endpoint | Mô tả |
|---|---|
| `GET /courses/discover` | Hiển thị danh sách các khóa học có thể tham gia (lọc ra các khóa đã đăng ký) |
| `POST /courses/<id>/enroll` | Ghi danh vào khóa học — thêm vào bảng quan hệ `enrollments` |
| `GET /courses/<id>` | Trang chi tiết khóa học dành cho sinh viên: xem tài liệu, danh sách bài tập và trạng thái nộp bài |
| `GET /courses/<id>/ask` | Hiển thị form đặt câu hỏi, kèm lịch sử các câu đã đặt trong khóa học |
| `POST /courses/<id>/ask` | Gửi câu hỏi (hỗ trợ **nhiều câu hỏi cùng lúc** trong một lần submit) kèm thông tin tài liệu tham chiếu và số trang |
| `GET /courses/<id>/assignment/<id>` | Hiển thị giao diện làm bài tập MCQ cho sinh viên |
| `POST /courses/<id>/assignment/<id>` | Nộp bài: chấm điểm tự động, lưu đáp án và kết quả (`score`) vào `AssignmentSubmission` |

---

### 3.3. Module Phát Hiện Lỗ Hổng Kiến Thức — `core/discovery.py` + `routes/discovery.py`

Đây là pipeline AI cốt lõi đầu tiên, xử lý toàn bộ luồng phân tích câu hỏi sinh viên.

#### Luồng Xử Lý (Pipeline):

```
[Câu hỏi "pending" của sinh viên]
           ↓
[Bước 1] identify_gaps_in_batch()   → Xác định lỗ hổng từng câu hỏi (batch=15)
           ↓ RAG context được lấy trước (query_course_content)
[Bước 2] accumulate_gaps()          → Gộp nhóm lỗ hổng đơn lẻ thành danh mục
           ↓
[Bước 3] classify_posts()           → Phân loại từng bài đăng vào danh mục
           ↓
[Bước 4] compute_metrics()          → Tính Coverage & Cohesion
           ↓
[Kết quả] {categories, classified_posts, knowledge_gaps}
```

#### Chi Tiết Các Bước:

**Bước 1 — `identify_gaps_in_batch()`:**
Gửi tối đa 15 bài đăng trong một prompt, yêu cầu LLM trích xuất *tất cả* lỗ hổng cho *từng bài* theo dạng mảng lồng nhau (`[[gaps bài 1], [gaps bài 2], ...]`). Nội dung tài liệu từ RAG được nhúng vào prompt để LLM hiểu đúng ngữ cảnh học thuật.

**Bước 2 — `accumulate_gaps()` / `_group_batch()`:**
Gộp các lỗ hổng đơn lẻ thành danh mục tổng quát. Nếu tổng số danh mục vượt quá 15 (do nhiều batch), hệ thống tiến hành thêm một vòng gộp cuối cùng. **Số lượng danh mục do LLM tự quyết định** dựa theo nội dung, không cố định.

**Bước 3 — `classify_posts()`:**
Phân loại từng bài đăng vào 0, 1 hoặc nhiều danh mục (`has_gap: true/false`), kết quả trả về theo cấu trúc JSON có chỉ mục.

**Bước 4 — `compute_metrics()` / `_assess_cohesion()`:**
- **Coverage:** Đếm số bài đăng thuộc mỗi danh mục.
- **Cohesion:** Gửi mẫu 5 bài đăng cho LLM đánh giá mức độ nhất quán theo thang 3 mức (Cao/Trung bình/Thấp).

#### Endpoint Web:

| Endpoint | Mô tả |
|---|---|
| `GET /discovery/<course_id>` | Hiển thị số lượng câu hỏi "pending" cần phân tích |
| `POST /discovery/<course_id>` | Kích hoạt pipeline (chạy ngầm), redirect đến trang chờ kết quả |
| `GET /discovery/<course_id>/results/<task_id>` | Polling kết quả — nếu hoàn thành: đánh dấu câu hỏi thành `processed`, lưu `KnowledgeGap` vào DB |

---

### 3.4. Module Duyệt Chuyên Gia — `routes/refinement.py`

Bước trung gian dành riêng cho **giảng viên** để hiệu chỉnh kết quả AI trước khi đưa vào sinh câu hỏi.

#### Chức năng:

| Hành động | Mô tả |
|---|---|
| **Xem kết quả** (`GET /refinement/<id>`) | Hiển thị danh sách tất cả các lỗ hổng AI phát hiện, kèm số lượng bài đăng và chỉ số Cohesion |
| **Đổi tên** (`action=rename`) | Giảng viên đặt lại tên danh mục lỗ hổng cho chính xác và chuyên nghiệp hơn |
| **Xóa** (`action=delete`) | Loại bỏ các danh mục không phù hợp hoặc quá chung chung |
| **Gộp** (`action=merge`) | Hợp nhất từ 2+ danh mục thành 1 với tên mới; Coverage và Posts được cộng lại |
| **Xác nhận** (`POST /refinement/<id>/confirm`) | Chốt danh sách lỗ hổng, chọn 1 gap và chuyển thẳng sang trang sinh LOP với dữ liệu mẫu |

> **Lưu ý thiết kế:** Dữ liệu kết quả Discovery và Refinement được lưu tạm trong **bộ nhớ in-process** (`_discovery_results` dict trong `services.py`), không phải database. Điều này cho phép chỉnh sửa linh hoạt mà không tạo ra các bản ghi trung gian; chỉ khi giảng viên xác nhận, kết quả cuối mới được ghi vào bảng `knowledge_gaps`.

---

### 3.5. Module Sinh Cơ Hội Học Tập (LOP) — `core/generation.py` + `routes/generation.py`

Pipeline AI thứ hai, toàn bộ vận hành trong luồng tiến trình nền (background thread).

#### Luồng Sinh LOP Đầy Đủ (6 Bước):

```
[Lỗ hổng + bài đăng mẫu + Loại LOP + Bloom + Độ khó]
           ↓
[Bước 1] brainstorm()         → CoT: Sinh 3+ ý tưởng câu hỏi đa dạng
           ↓
[Bước 2] select_best_ideas()  → Chọn ý tưởng tốt nhất theo 4 tiêu chí
           ↓
[Bước 3] generate_and_refine()
          ├── _generate()     → Tạo LOP bản nháp đầu (MCQ hoặc non-MCQ)
          └── _refine() x2    → Self-Refine 2 vòng, phê bình & tự sửa
           ↓
[Bước 4] adjust_difficulty()  → Điều chỉnh nội dung theo mức độ Dễ/TB/Khó
           ↓
[Bước 5] evaluate()           → AI Guardrails: chấm điểm trên 4 tiêu chí
           ↓
[Bước 6] attribute_sources()  → Truy vết nguồn tài liệu đã dùng (RAG attribution)
           ↓
[Kết quả] {lop, evaluation, source_attribution, metadata}
```

#### Các Loại LOP Được Hỗ Trợ (`LOP_TYPES`):

| Mã | Mô tả |
|---|---|
| `MCQ` | Câu hỏi trắc nghiệm với 4 lựa chọn, 1 đáp án đúng, giải thích chi tiết |
| `worked_example` | Ví dụ minh họa có lời giải từng bước |
| `explanation` | Giải thích khái niệm kèm ví dụ cụ thể |
| `exercise` | Bài tập thực hành tự luận |
| `case_study` | Tình huống thực tế yêu cầu phân tích |

#### Thang Bloom Được Hỗ Trợ:

| Mã | Cấp độ |
|---|---|
| `nho` | Nhớ & Nhận biết (Bloom 1) |
| `hieu` | Hiểu (Bloom 2) |
| `ap_dung` | Áp dụng (Bloom 3) |
| `phan_tich` | Phân tích (Bloom 4) |
| `danh_gia` | Đánh giá & Tổng hợp (Bloom 5-6) |

#### Endpoint Web:

| Endpoint | Vai trò | Mô tả |
|---|---|---|
| `GET/POST /generation/<id>` | Giảng viên | Form chọn lỗ hổng, loại LOP, Bloom, độ khó; kích hoạt pipeline |
| `GET /generation/<id>/view/<task_id>` | Giảng viên | Xem kết quả LOP; tự động lưu vào DB nếu task hoàn thành |
| `GET /generation/dashboard/<id>` | Giảng viên | Danh sách toàn bộ LOP và bài tập đã tạo cho khóa học |
| `GET/POST /generation/create_assignment/<id>` | Giảng viên | Chọn câu hỏi từ LOP để tổng hợp thành bài tập |
| `GET /generation/assignment_dashboard/<id>` | Giảng viên | Thống kê chi tiết một bài tập: tỉ lệ hoàn thành, câu sai nhiều nhất |
| `GET/POST /generation/edit/<lop_id>` | Giảng viên | Chỉnh sửa nội dung JSON của LOP thủ công |

---

### 3.6. Module Xử Lý Tài Liệu & RAG — `core/ingestion.py`

Đây là tầng cơ sở hạ tầng dữ liệu cho toàn bộ pipeline AI, xử lý từ việc tiếp nhận file PDF đến cung cấp ngữ cảnh cho LLM.

#### Chức năng:

**Upload & Xử Lý PDF (`upload_document`):**
- Tạo bản ghi Document trong DB với `status=processing`.
- Khởi chạy luồng ngầm (`threading.Thread`) để xử lý PDF.
- **Ưu tiên 1:** Dùng thư viện `PageIndex`: trích xuất cấu trúc phân cấp (chương, mục, tiểu mục) thành các Node có `node_id`, `title`, `content`, `summary`, thông tin trang.
- **Ưu tiên 2 (Fallback):** Nếu PageIndex thất bại, dùng `PyPDF2` để trích xuất text thô theo từng trang.
- Lưu tất cả các Node vào bảng `document_nodes`.
- Cập nhật trạng thái Document thành `completed` hoặc `error`.

**2-Step Reasoning RAG (`_query_core`):**
- **Bước 1:** Xây dựng JSON Mục lục (ToC) từ DB, gửi cho LLM chọn tối đa 5 `node_id` liên quan.
- **Bước 2:** Truy vấn DB lấy nội dung đầy đủ của các Node đó, ghép lại thành context block.
- Trả về `(content_str, sources_list)` — `sources_list` chứa thông tin file, trang, tiêu đề mục.

**Quản Lý Tài Liệu:**
- `list_documents(course_id)` — Liệt kê tài liệu kèm trạng thái xử lý.
- `delete_document(doc_id)` — Xóa khỏi DB (cascade xóa cả các Node liên quan).
- `check_document_status(doc_id)` — Kiểm tra trạng thái xử lý (dùng cho API polling).
- `get_course_summary(course_id)` — Tóm tắt dạng text về tài liệu của khóa học.

---

### 3.7. Module Analytics — `routes/analytics.py`

Dashboard phân tích toàn diện dành riêng cho **giảng viên**, cung cấp cái nhìn đa chiều về hiệu suất lớp học.

#### Dashboard Tổng Quan (`GET /analytics/<course_id>`):

| Nhóm chỉ số | Dữ liệu cung cấp |
|---|---|
| **Sinh viên** | Tổng số, số đang hoạt động (đã nộp ít nhất 1 bài) |
| **Tài liệu** | Số tài liệu, tổng số trang đã xử lý |
| **Câu hỏi** | Tổng số, số câu đang chờ phân tích |
| **Lỗ hổng** | Số danh mục KG đã phát hiện |
| **Bài tập** | Số bài tập, tỉ lệ nộp bài, điểm trung bình lớp |
| **Phân phối điểm** | Histogram 11 cột (0→10 điểm) |
| **Top câu sai** | 10 câu hỏi có tỉ lệ sai cao nhất, gắn với danh mục lỗ hổng |
| **Gap Performance** | Biểu đồ tỉ lệ sai theo từng Knowledge Gap |
| **Tiến độ từng sinh viên** | Điểm TB, số bài hoàn thành, danh sách lỗ hổng yếu nhất (top 3) |

#### Chi Tiết Sinh Viên (`GET /analytics/<course_id>/student/<student_id>`):

- Xem kết quả chi tiết từng bài tập của một sinh viên cụ thể.
- Liệt kê từng câu trả lời sai: câu hỏi, đáp án sinh viên chọn, đáp án đúng.
- Phân tích độ thành thạo theo từng Knowledge Gap (biểu đồ radial/bar).
- Phân loại mức độ: **Tốt** (≥70%), **Cần cải thiện** (40-69%), **Yếu** (<40%).

---

### 3.8. Module API JSON — `routes/api.py`

API nội bộ phục vụ giao tiếp AJAX giữa trình duyệt và backend.

| Endpoint | Mô tả |
|---|---|
| `GET /api/task/<task_id>` | Trả về trạng thái tác vụ nền (`running`, `done`, `error`) và kết quả |
| `GET /api/upload-status/<doc_id>` | Kiểm tra trạng thái xử lý PDF của một tài liệu cụ thể |

---

### 3.9. Lớp Dữ Liệu — `database/models.py` & `database/repository.py`

#### Mô Hình Dữ Liệu (ERD Tóm Tắt):

```
User ──< enrollments >── Course
User ──< Question
Course ──< Document ──< DocumentNode
Course ──< KnowledgeGap ──< LearningOpportunity
Course ──< Assignment ──< AssignmentSubmission >── User
User ──< ExerciseSubmission >── LearningOpportunity
```

#### Bảng Dữ Liệu Chính:

| Bảng | Vai trò |
|---|---|
| `users` | Lưu tài khoản (email, name, password_hash, role) |
| `enrollments` | Bảng quan hệ nhiều-nhiều: sinh viên ↔ khóa học |
| `courses` | Thông tin khóa học (name, code, description, owner_id) |
| `questions` | Câu hỏi của sinh viên (`status`: pending/processed) |
| `documents` | Tài liệu PDF đã upload (`status`: processing/completed/error) |
| `document_nodes` | Các node phân cấp được trích xuất từ PDF (dùng cho RAG) |
| `knowledge_gaps` | Các danh mục lỗ hổng kiến thức đã được xác nhận |
| `learning_opportunities` | Các LOP đã sinh ra (type, bloom_level, difficulty, content JSON) |
| `assignments` | Bài tập tổng hợp từ các LOP (content JSON gồm danh sách câu hỏi) |
| `assignment_submissions` | Bài làm của sinh viên (answers JSON, score, status) |
| `exercise_submissions` | Theo dõi trạng thái làm bài tập rời (pending/completed) |

#### Repository Pattern:

Mỗi entity có một class Repository độc lập (`UserRepo`, `CourseRepo`, `QuestionRepo`, ...) đảm nhận toàn bộ thao tác với DB, giúp các Route Blueprint hoàn toàn không chứa SQL hay ORM call trực tiếp.

---

### 3.10. Module Dịch Vụ Nền — `services.py`

Tầng trung gian quan trọng được cài đặt để tránh circular import và cung cấp các singleton dùng chung.

#### Chức năng:

**Singleton Services (`get_services()`):**
Khởi tạo lười (`lazy initialization`) ba đối tượng lõi chỉ một lần duy nhất trong vòng đời ứng dụng:
- `CourseIngestion` — Xử lý tài liệu & RAG
- `KnowledgeGapDiscovery` — Pipeline phát hiện lỗ hổng
- `LOPGenerator` — Pipeline sinh LOP

**Background Task Manager (`run_task`, `get_task`):**
- `run_task(task_id, fn, *args)`: Chạy hàm `fn` trong một `daemon thread` riêng. Capture `Flask app context` và tiêm vào thread để SQLAlchemy hoạt động đúng.
- `get_task(task_id)`: Trả về dict trạng thái `{status, result, error}`.

**Discovery Results Cache (`save_discovery_results`, `get_discovery_results`):**
Bộ nhớ đệm in-process lưu kết quả Discovery tạm thời để module Refinement đọc và chỉnh sửa mà không cần ghi DB.

---

### 3.11. Module LLM Client — `core/utils.py`

Lớp trừu tượng hóa toàn bộ giao tiếp với LLM, đảm bảo tính ổn định.

#### Cơ chế `generate_with_retry()`:

- **Endpoint:** HTTP POST đến Ollama API (`/api/generate`) với `stream=True`.
- **Throttling:** `_throttle()` đảm bảo khoảng cách tối thiểu **7 giây** giữa hai lần gọi API liên tiếp để tránh bị rate-limit.
- **Exponential Backoff:** Khi gặp lỗi, tự động chờ ban đầu 10 giây, tăng gấp đôi sau mỗi lần thử, tối đa **5 lần thử**.
- **Streaming Processing:** Đọc và ghép nối từng chunk JSON từ response stream Ollama.
- **DummyResponse:** Trả về một object có thuộc tính `.text` — giao diện tương thích ngược toàn bộ pipeline nếu cần thay LLM backend.

---

## 4. Tổng Hợp Chức Năng Theo Vai Trò Người Dùng

### 4.1. Chức Năng Của Giảng Viên (Instructor)

| Nhóm | Chức năng |
|---|---|
| **Quản lý khóa học** | Tạo khóa học mới; xem danh sách lớp; upload/xóa tài liệu PDF |
| **Phân tích lỗ hổng** | Kích hoạt pipeline phát hiện KG từ câu hỏi sinh viên; xem kết quả phân tích |
| **Duyệt kết quả AI** | Đổi tên, xóa, gộp các danh mục lỗ hổng do AI đề xuất |
| **Sinh LOP** | Chọn lỗ hổng, cấu hình thông số (loại, Bloom, độ khó); theo dõi tiến trình sinh |
| **Quản lý bài tập** | Tạo bài tập từ LOP; theo dõi kết quả toàn lớp; xem chi tiết từng câu sai |
| **Chỉnh sửa LOP** | Sửa nội dung JSON của LOP thủ công |
| **Phân tích lớp học** | Xem dashboard tổng quan; phân tích từng sinh viên; biểu đồ phân phối điểm |

### 4.2. Chức Năng Của Sinh Viên (Student)

| Nhóm | Chức năng |
|---|---|
| **Khám phá & Đăng ký** | Xem danh sách khóa học có thể tham gia; tự đăng ký vào khóa học |
| **Xem nội dung** | Vào trang chi tiết khóa học; xem danh sách tài liệu đã upload; xem bài tập được giao |
| **Đặt câu hỏi** | Đặt một hoặc nhiều câu hỏi trong một lần gửi; đính kèm tài liệu tham chiếu và số trang; xem lịch sử câu hỏi của bản thân |
| **Làm bài tập** | Xem đề bài MCQ; chọn đáp án; nộp bài để chấm điểm tự động |
| **Theo dõi tiến trình** | Xem điểm số (`score`) từng bài tập ngay trên trang chi tiết khóa học; xem trạng thái nộp bài (`pending`/`completed`) |

---

## 5. Các Kỹ Thuật Nâng Cao Đã Sử Dụng

### 5.1. Balanced Bracket JSON Extraction (Trích Xuất JSON Chống Lỗi)

**Vị trí:** Hàm `_extract_json(text, target)` tại `core/discovery.py` và `core/generation.py`.

Thay vì parse trực tiếp text từ LLM (dễ hỏng do LLM thêm markdown, giải thích thừa), hệ thống cài đặt thuật toán **đếm dấu ngoặc cân bằng** với đầy đủ xử lý escape character và string literal để định vị chính xác ranh giới của JSON object/array.

**Ý nghĩa:** Loại bỏ hoàn toàn khả năng crash do `JSONDecodeError` khi LLM trả về output không sạch.

### 5.2. 2-Step Reasoning-Based RAG (RAG Suy Luận 2 Bước)

**Vị trí:** `CourseIngestion._query_core()` tại `core/ingestion.py`.

Thay vì embedding + cosine similarity thông thường, quy trình:
1. Gửi **Mục lục JSON** (ToC) của toàn bộ tài liệu cho LLM để suy luận.
2. LLM chỉ định **chính xác ID các Node** cần thiết.
3. Mới truy vấn DB để lấy **nội dung đầy đủ** chỉ các Node đó.

**Ý nghĩa:** Tiết kiệm token, giữ được cấu trúc logic của tài liệu, lọc nhiễu vượt trội so với RAG cắt chunk cố định. Không cần infrastructure Vector Database.

### 5.3. Background Threading + App Context Injection

**Vị trí:** `services.py` — `run_task()`.

Flask app context được capture thủ công từ luồng chính và tiêm vào daemon thread thông qua `with app.app_context()`, cho phép SQLAlchemy hoạt động đúng bên trong thread. Giao diện polling bằng cách gọi `GET /api/task/<task_id>`.

**Ý nghĩa:** Xử lý LLM call có thể mất 30-120 giây mà không block web server, không gây timeout trình duyệt.

### 5.4. Chain-of-Thought + Multi-Round Self-Refine

**Vị trí:** `LOPGenerator.brainstorm()` và `LOPGenerator._refine()` tại `core/generation.py`.

Quá trình sinh câu hỏi trải qua **5+ lần gọi LLM riêng biệt**: Brainstorm (CoT) → Chọn lọc → Sinh bản nháp → Self-Refine lần 1 → Self-Refine lần 2 → Điều chỉnh độ khó → Đánh giá Guardrails. Mỗi vòng Refine bắt LLM phê bình chính output cũ của nó theo 5 tiêu chí rồi tự cải thiện.

**Ý nghĩa:** Loiọ bỏ triệt để các câu hỏi nông cạn, các distractors (đáp án sai) vô nghĩa — output cuối đạt tiêu chuẩn sư phạm hàn lâm.

### 5.5. Global Throttle + Exponential Backoff (Rate Limiting)

**Vị trí:** `core/utils.py` — `_throttle()` và `generate_with_retry()`.

Biến `_last_call_time` ở cấp module (global) đảm bảo khoảng cách tối thiểu 7 giây *trên toàn ứng dụng* giữa các lần gọi API. Kết hợp với retry exponential backoff (10s → 20s → 40s → ...).

**Ý nghĩa:** Tránh lỗi rate-limit 429/503 từ LLM server mà không cần can thiệp thủ công ở từng điểm gọi trong codebase.

### 5.6. Lazy Singleton Pattern (Khởi Tạo Lười)

**Vị trí:** `services.py` — `get_services()`.

Ba service lõi (`CourseIngestion`, `KnowledgeGapDiscovery`, `LOPGenerator`) chỉ được khởi tạo khi lần đầu được gọi tới, không phải lúc import module. Tránh circular import giữa `app.py` → `routes/` → `services.py`.

**Ý nghĩa:** Ứng dụng khởi động nhanh hơn; logic khởi tạo phức tạp được tách hoàn toàn khỏi Application Factory.

### 5.7. Reverse Lookup Map Trong Analytics

**Vị trí:** `routes/analytics.py` — `_build_lop_gap_map()`.

Dữ liệu bài tập cũ có thể không chứa trường `gap_title`. Hàm này xây dựng một Hash Map `{cau_hoi_text → gap_title}` bằng cách đọc ngược từ bảng `learning_opportunities`, cho phép gắn nhãn Knowledge Gap cho mọi câu hỏi trong assignment dashboard dù được tạo theo format nào.

**Ý nghĩa:** Đảm bảo backward-compatibility và tính nhất quán của biểu đồ phân tích mà không cần migration DB.

### 5.8. Fallback Pipeline Handling (Cơ Chế Dự Phòng Rớt Bậc)

**Vị trí:** `core/ingestion.py` — `upload_document()` → `_fallback_extract()`.

PageIndex là lớp xử lý ưu tiên; nếu gặp lỗi bất kỳ (định dạng PDF phức tạp, lỗi mạng nội bộ...), hệ thống tự động chuyển xuống PyPDF2 để trích xuất text thô theo trang. Người dùng không nhận thấy sự khác biệt về trải nghiệm (chỉ khác về chất lượng cấu trúc).

**Ý nghĩa:** Đảm bảo tính **High Availability** cho tính năng upload tài liệu — hệ thống không bao giờ hoàn toàn từ chối xử lý một file PDF.

---

## 6. Kết Luận

Hệ thống KG2M Demo triển khai thành công một vòng lặp GiảngViên–AI–SinhViên khép kín, trong đó:

- **Sinh viên** là nguồn dữ liệu đầu vào thực sự (câu hỏi, bài làm).
- **AI Pipeline** tự động hoá các bước nhận diện và phân tích vốn đòi hỏi nhiều công sức thủ công.
- **Giảng viên** đóng vai trò người giám sát cuối cùng, duyệt và tinh chỉnh kết quả AI trước khi phát hành nội dung đến sinh viên.
- **Analytics** đóng vòng lặp bằng cách đo lường hiệu quả và phản ánh lại những lỗ hổng còn tồn tại.

Nền tảng kỹ thuật được xây dựng cẩn thận với các cơ chế phòng ngừa lỗi đa lớp (retry, fallback, JSON recovery), đảm bảo hệ thống vận hành ổn định ngay cả khi tích hợp với các mô hình ngôn ngữ tự host có độ trễ và tính bất định cao.
