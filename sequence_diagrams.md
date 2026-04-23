# Phân tích Luồng Hoạt Động Hệ Thống KG2M (Sequence Diagrams)

Dựa trên việc đọc và phân tích mã nguồn Controller (`routes/courses.py`, `routes/discovery.py`, `routes/generation.py`) cùng với luồng thao tác của các Services, dưới đây là chi tiết phân tích và kịch bản Sequence Diagram cho 4 luồng (Flows) chính mà bạn yêu cầu.

## 4.2.5.1 Luồng nạp và xử lý tài liệu (Document Ingestion)

Mục đích: Giảng viên đưa học liệu dạng PDF lên hệ thống để RAG (PageIndex) phân tách thành các Node dữ liệu chuẩn bị cho quá trình tạo sinh và trả lời ngữ cảnh.

**Các bước chính:**
1. **Giảng viên** tải file tài liệu (PDF) từ giao diện máy khách.
2. **Hệ thống (Router)** tiếp nhận file vật lý dể lưu vào thư mục `uploads/course_id/`.
3. Gọi **IngestionService** thực thi hàm `upload_document`.
4. Dịch vụ đưa file cho **PageIndex (RAG Pipeline)** để trích xuất text và băm nhỏ thành các document chunks (nodes).
5. Sau khi xử lý xong, thông tin được lưu xuống DB ở 2 bảng `documents` và `document_nodes`.
6. Trả trạng thái kèm thông điệp (Flash) thông báo thành công ở phía Giao diện (View).

```mermaid
sequenceDiagram
    actor Instructor
    participant UI as Giao diện Web
    participant Router as Tuyến /courses/<id>/upload
    participant Svc as Ingestion Service
    participant RAG as PageIndex Pipeline
    participant DB as Tiên lập CSDL
    
    Instructor->>UI: Chọn File PDF và Cấu hình loại
    UI->>Router: POST file form data
    Router->>Router: Lưu file tạm tại /uploads/{course_id}
    Router->>Svc: upload_document(filepath, course_id)
    Svc->>RAG: Gọi pipeline trích xuất Text & Index
    RAG-->>Svc: Trả về chuỗi các chunks (nodes)
    Svc->>DB: Lưu bản ghi bảng Documents
    Svc->>DB: Lưu danh sách bảng Document_Nodes
    Svc-->>Router: Trả về Entry Info
    Router-->>UI: Redirect (kèm Flash success)
    UI-->>Instructor: Thông báo upload & index thành công
```

## 4.2.5.2 Luồng phát hiện lỗ hổng (Knowledge Gap Discovery)

Mục đích: Hệ thống tự động gom nhóm các câu hỏi chưa xử lý (pending) của sinh viên trong khóa học để gửi cho AI Language Model, từ đó khái quát lên "Lỗ hổng kiến thức".

**Các bước chính:**
1. **Giảng viên** vào trang Quản trị lỗ hổng và nhấn nút Phát hiện mới.
2. **Router** truy vấn `QuestionRepo` lấy danh sách câu hỏi đang `pending`.
3. Router khởi tạo tiến trình nền (Background Task) thông qua qua cơ chế `run_task`, chuyển nội dung sang cho **Discovery AI Service**.
4. Controller trả về ngay giao diện chờ (Polling loading) để không bị nghẽn (timeout) khi AI chạy. Giao diện thỉnh thoảng gọi lại API trạng thái `results/[task_id]`.
5. Sau khi AI trả về kết quả (JSON định dạng các lỗ hổng), **Router** duyệt lưu trữ nhóm lỗ hổng vảo bảng `knowledge_gaps`. Đồng thời đánh dấu `status = 'processed'` cho các câu hỏi tương ứng.

```mermaid
sequenceDiagram
    actor Instructor
    participant UI as Giao diện Web
    participant Routes as Tuyến /discovery/<id>
    participant DB as Cơ sở dữ liệu
    participant AI as Discovery AI Service
    
    Instructor->>UI: Yêu cầu "Phát hiện lỗ hổng"
    UI->>Routes: POST /discovery/<course_id>
    Routes->>DB: get_pending_for_course()
    DB-->>Routes: Danh sách câu hỏi Pending
    Routes->>AI: run_task(discover(posts))
    Routes-->>UI: Khởi tạo Task, Redirect tới trang chờ (Polling)
    
    loop Chờ tiến trình AI hoàn tất
        UI->>Routes: GET /results/{task_id}
        alt Đang xử lý
            Routes-->>UI: Hiển thị Loading
        end
    end
    
    AI-->>Routes: Kết quả Lỗ hổng Kiến thức (JSON)
    UI->>Routes: GET /results/{task_id} (thành công)
    Routes->>DB: Đánh dấu câu hỏi = "processed"
    Routes->>DB: Insert bản ghi mới vào knowledge_gaps
    Routes-->>UI: Render View với danh sách Lỗ hổng
```

## 4.2.5.3 Luồng tạo sinh cơ hội học tập (Learning Opportunity Generation)

Mục đích: Từ một "Lỗ hổng", giảng viên thiết lập cấu hình mức độ khó (Bloom level), số lượng, dạng bài (Trắc nghiệm MCQ). Hệ thống gọi AI để tạo ra các bài tập tự động được nạp bằng Document RAG Context.

**Các bước chính:**
1. **Giảng viên** chọn Lỗ hổng mục tiêu, yêu cầu Mức độ Bloom (Ví dụ: Vận dụng / Application) và bấm "Tạo sinh".
2. Hệ thống gọi background task cho `generator.generate(...)`.
3. AI kết hợp ngữ cảnh là các logs sinh viên thắc mắc và tài liệu (Course Context) để thiết kế câu hỏi dạng MCQs.
4. Giao diện Polling gọi API trả về kết quả cấu trúc bài.
5. Khi Task thành công, **Router** lưu trữ chuỗi JSON của các câu hỏi vào model tạo thành các `LearningOpportunity` (gắn liền vào `KnowledgeGap` cha).

```mermaid
sequenceDiagram
    actor Instructor
    participant UI as Giao diện Web
    participant Router as Tuyến /generation/<id>
    participant AI as Generator AI Service
    participant DB as Cơ sở dữ liệu
    
    Instructor->>UI: Chọn Lỗ hổng, Mức Bloom, Khó, Số lượng
    UI->>Router: POST /generation/<course_id>
    Router->>AI: run_task(generate(gap_info, configs))
    Router-->>UI: Bắt đầu Polling quá trình sinh
    
    loop Chờ tiến trình trả về câu hỏi
        UI->>Router: GET /view/{task_id}
        alt Đang xử lý
            Router-->>UI: Hiển thị đang Generate
        end
    end
    
    AI-->>Router: Bộ Array Câu hỏi/Bài tập (JSON)
    UI->>Router: GET /view/{task_id} (thành công)
    Router->>DB: Quét và Insert vào cấu trúc LearningOpportunity
    Router-->>UI: Render Component Danh sách câu hỏi AI vừa tạo
```

## 4.2.5.4 Luồng sinh viên làm bài tập (Student Assignment / Exercise flow)

Mục đích: Sinh viên truy cập vào bài kiểm tra (Assignment) đã được gộp từ các Cơ hội học tập, sau đó làm trực tiếp trên giao diện trình duyệt. Nhấn nộp và được chấm điểm tự động.

**Các bước chính:**
1. **Sinh viên** mở giao diện chi tiết Bài Khảo Sát / Assignment.
2. Web gọi Router GET dữ liệu -> Router tìm thấy trạng thái `pending` của `AssignmentSubmission` (hoặc tạo mới nếu chưa tồn tại).
3. Đổ HTML hiển thị các câu hỏi trắc nghiệm ra giao diện.
4. Chọn đáp án trên form, bấm Gửi (POST).
5. **Router** đánh giá (Grading) bằng logic: lấy Form Input (`student_choice`) kiểm tra khớp với `dap_an_dung` được parse từ trường JSON lưu tại bảng Submission / Assignment.
6. Tính được tổng điểm `score_str` => Ghi đè vào submission. Cập nhật `status = 'completed'`.

```mermaid
sequenceDiagram
    actor Student
    participant UI as Giao diện Web
    participant Router as Tuyến /assignment/<id>
    participant DB as Cơ sở dữ liệu
    
    Student->>UI: Truy cập Bài tập (Assignment)
    UI->>Router: GET /assignment/<assignment_id>
    Router->>DB: Lấy/Tạo AssignmentSubmission (status: pending)
    DB-->>Router: Submission Record & JSON Câu hỏi
    Router-->>UI: Hiển thị form Câu hỏi
    
    Student->>UI: Chọn đáp án A/B/C/D
    Student->>UI: Nhấn "Nộp bài"
    UI->>Router: POST Form Data (q_0, q_1, ...)
    
    activate Router
    Router->>Router: Chấm điểm tự động (so sánh "dap_an_dung" từ JSON)
    Router->>Router: Tính Total correct_count
    Router->>DB: update AssignmentSubmission (answers_json, score, status=completed)
    deactivate Router
    
    Router-->>UI: Redirect với Flash message (Điểm số)
    UI-->>Student: Giao diện kết quả Điểm (VD: Nộp bài thành công! Điểm: 8/10)
```

## 4.2.5.5 Luồng giảng viên xem thống kê (Instructor Analytics / Dashboard)

Mục đích: Giảng viên theo dõi, phân tích tình hình học tập của sinh viên thông qua các bài kiểm tra, tiến độ hoàn thành, và hiệu suất đối với từng "Lỗ hổng kiến thức".

**Các bước chính:**
1. **Giảng viên** truy cập vào giao diện Dashboard Thống kê của khóa học (`/analytics/<course_id>`).
2. **Router (`analytics_bp`)** tiếp nhận yêu cầu và xác thực quyền `instructor`.
3. **Router** truy vấn Cơ sở dữ liệu (DB) để lấy tổng hợp dữ liệu từ các danh mục: Sinh viên enrolled, Câu hỏi, KnowledgeGaps, Assignments, và AssignmentSubmissions (những bài đã `completed`).
4. **Router** thực hiện phân tích số liệu: 
   - Điểm số trung bình (Overall avg score).
   - Tỷ lệ hoàn thành (Completion %).
   - Tỷ lệ trả lời sai theo từng Lỗ hổng (Knowledge Gap wrong rates).
   - Tiến độ thực hiện bài tập của từng sinh viên (Student progress).
5. Dữ liệu sau khi tổng hợp được truyền về cho **Giao diện Web**.
6. **Giao diện Web** (`dashboard.html`) render các biểu đồ (charts) phân bố điểm, tỷ lệ sai theo lỗ hổng và các bảng biểu báo cáo chi tiết.

```mermaid
sequenceDiagram
    actor Instructor
    participant UI as Giao diện Web
    participant Router as Tuyến /analytics/<id>
    participant DB as Cơ sở dữ liệu
    
    Instructor->>UI: Truy cập xem Thống kê khóa học
    UI->>Router: GET /analytics/<course_id>
    
    activate Router
    Router->>Router: Xác thực quyền (Require Instructor)
    Router->>DB: Truy vấn Users, Gaps, Assignments, Submissions
    DB-->>Router: Trả về tập dữ liệu thô
    Router->>Router: Tổng hợp thống kê (Điểm TB, Tỷ lệ sai theo Gap, Tiến độ)
    Router-->>UI: Render View kèm Dữ liệu Dashboard
    deactivate Router
    
    UI->>UI: Vẽ biểu đồ (Charts) & Hiển thị Bảng số liệu
    UI-->>Instructor: Hiển thị giao diện Dashboard phân tích
```
