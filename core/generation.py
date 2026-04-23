"""
KG2M - core/generation.py
Sinh cơ hội học tập có mục tiêu (Learning Opportunities).
Sử dụng CoT + Self-Refine + PageIndex RAG multi-doc.
Toàn bộ prompt viết tiếng Việt, chi tiết.
"""

import json
import re
from core.ingestion import CourseIngestion
from core.utils import generate_with_retry


def _extract_json(text: str, target: str = "object") -> str | None:
    """
    Trích xuất JSON object ({...}) hoặc array ([...]) từ text
    bằng balanced bracket counting — xử lý đúng JSON lồng nhau.
    target: "object" cho {}, "array" cho []
    """
    open_char = "{" if target == "object" else "["
    close_char = "}" if target == "object" else "]"
    start = text.find(open_char)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


LOP_TYPES = {
    "MCQ": "Câu hỏi trắc nghiệm (MCQ)",
}

BLOOM_LEVELS = {
    "nho": "Nhớ & Nhận biết (Bloom cấp 1) - kiểm tra định nghĩa, ký hiệu, quy tắc cơ bản",
    "hieu": "Hiểu (Bloom cấp 2) - giải thích khái niệm bằng lời riêng",
    "ap_dung": "Áp dụng (Bloom cấp 3) - dùng kiến thức giải bài toán mới",
    "phan_tich": "Phân tích (Bloom cấp 4) - so sánh, phân tách, tìm lý do",
    "danh_gia": "Đánh giá & Tổng hợp (Bloom cấp 5-6) - phán xét, thiết kế giải pháp",
}

DIFFICULTY = {
    "de": "Dễ - sinh viên mới học chủ đề này",
    "trung_binh": "Trung bình - sinh viên đã học nhưng chưa thành thạo",
    "kho": "Khó - sinh viên cần suy nghĩ sâu, có thể gặp trường hợp đặc biệt",
}


class LOPGenerator:
    def __init__(
        self,
        gemini_api_key: str,
        ingestion: CourseIngestion,
        model_name: str = "gpt-oss:20b",
    ):
        self.model_name = model_name
        self.ingestion = ingestion

    # ── Bước 1: Nảy sinh ý tưởng (CoT) ─────────────────────────────────────

    def brainstorm(
        self,
        knowledge_gap: str,
        sample_posts: list,
        lop_type: str,
        bloom_level: str,
        course_name: str = "Khoa học Máy tính",
        n_ideas: int = 3,
        course_ctx: str = "",
    ) -> list:
        posts_text = "\n".join(f"  - {p[:250]}" for p in sample_posts[:4])
        bloom_desc = BLOOM_LEVELS.get(bloom_level, bloom_level)
        lop_desc = LOP_TYPES.get(lop_type, lop_type)

        prompt = f"""Bạn là chuyên gia thiết kế câu hỏi đánh giá học thuật cho các khóa học {course_name} tại đại học.

LỖ HỔNG KIẾN THỨC CẦN PHÁT HIỆN:
"{knowledge_gap}"

BÀI ĐĂNG THỰC TẾ CỦA SINH VIÊN CHO THẤY LỖ HỔNG NÀY:
{posts_text}

LOẠI CƠ HỘI HỌC TẬP CẦN TẠO: {lop_desc}
CẤP ĐỘ TƯ DUY (Bloom): {bloom_desc}

TÀI LIỆU KHÓA HỌC THAM KHẢO (Nếu có):
---
{course_ctx[:2000]}
---

NHIỆM VỤ:
Hãy suy nghĩ từng bước (Chain-of-Thought) để nảy sinh {n_ideas} Ý TƯỞNG KHÁC NHAU cho {lop_desc} dựa trên tài liệu khóa học.

CHUỖI SUY NGHĨ (thực hiện trong đầu trước khi viết kết quả):
Bước A - Phân tích lỗ hổng: Sinh viên chính xác không hiểu điều gì? Họ nhầm lẫn ở đâu?
Bước B - Xác định loại bài: Dạng tình huống/ngữ cảnh nào sẽ phơi bày lỗ hổng đó tốt nhất?
Bước C - Thiết kế nội dung: Cần kiểm tra khái niệm cụ thể nào? Câu trả lời sai sẽ xuất phát từ hiểu lầm gì?
Bước D - Đa dạng hóa: Mỗi ý tưởng dùng bối cảnh/ví dụ KHÁC NHAU để tránh lặp lại.

YÊU CẦU CHO MỖI Ý TƯỞNG:
- Phải trực tiếp nhắm vào đúng lỗ hổng kiến thức, KHÔNG phải chủ đề chung chung
- Có bối cảnh thực tế, cụ thể (không trừu tượng)
- Phù hợp với cấp độ tư duy Bloom đã chỉ định
- Viết bằng tiếng Việt

TRẢ VỀ: Chỉ mảng JSON hợp lệ, không giải thích, không markdown:
[
  {{
    "tieu_de": "Tên ngắn của ý tưởng",
    "mo_ta": "Mô tả ý tưởng này làm gì và tại sao nhắm đúng lỗ hổng",
    "boi_canh": "Tình huống/ví dụ cụ thể sẽ dùng",
    "khai_niem_kiem_tra": "Khái niệm cốt lõi được kiểm tra"
  }}
]

JSON:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "array")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        return [{"tieu_de": f"Ý tưởng {i+1}", "mo_ta": "", "boi_canh": "", "khai_niem_kiem_tra": knowledge_gap}
                for i in range(n_ideas)]

    # ── Bước 2: Chọn ý tưởng tốt nhất ──────────────────────────────────────

    def select_best_ideas(self, ideas: list, knowledge_gap: str, num_questions: int = 1) -> list:
        if len(ideas) <= num_questions:
            return ideas

        ideas_block = "\n\n".join(
            f"Ý TƯỞNG {i+1}:\n  Tiêu đề: {idea.get('tieu_de')}\n  Mô tả: {idea.get('mo_ta')}\n  Bối cảnh: {idea.get('boi_canh')}"
            for i, idea in enumerate(ideas)
        )

        prompt = f"""Bạn đang chọn {num_questions} ý tưởng tốt nhất để thiết kế cơ hội học tập cho lỗ hổng:
"{knowledge_gap}"

CÁC Ý TƯỞNG ĐỀ XUẤT:
{ideas_block}

TIÊU CHÍ ĐÁNH GIÁ (theo thứ tự ưu tiên):
1. MỨC ĐỘ CHÍNH XÁC: Ý tưởng có nhắm đúng VÀO ĐÚNG lỗ hổng kiến thức không, hay chỉ liên quan gián tiếp?
2. PHÂN BIỆT RÕ RÀNG: Câu hỏi/bài tập có câu trả lời đúng rõ ràng, không mơ hồ không?
3. GIÁ TRỊ SƯ PHẠM: Khi làm xong, sinh viên có HỌC ĐƯỢC gì từ bài này không (không chỉ đúng/sai)?
4. TÍNH THỰC TIỄN: Bối cảnh có gần gũi, dễ hình dung với sinh viên CNTT không?

TRẢ VỀ: Chỉ trả về một mảng JSON (json array) chứa các chỉ số gốc (dạng số nguyên 0-based index) của các ý tưởng được chọn, không giải thích gì thêm:
[0, 2]

JSON:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "array")
        if extracted:
            try:
                indices = json.loads(extracted)
                if isinstance(indices, list):
                    selected = [ideas[min(int(idx), len(ideas) - 1)] for idx in indices[:num_questions]]
                    if selected:
                        return selected
            except (json.JSONDecodeError, ValueError, IndexError):
                pass
        return ideas[:num_questions]

    # ── Bước 3: Sinh và tinh chỉnh với RAG ──────────────────────────────────

    def generate_and_refine(
        self,
        knowledge_gap: str,
        idea: dict,
        course_id: str,
        lop_type: str,
        bloom_level: str,
        course_name: str = "Khoa học Máy tính",
        n_refine: int = 2,
    ) -> tuple:
        """
        Sinh LOP ban đầu, sau đó tự tinh chỉnh (Self-Refine).
        Trả về (lop_dict, sources_list) — sources chứa thông tin file/mục RAG đã dùng.
        """
        # RAG: truy vấn với sources để biết LLM lấy nội dung từ đâu
        rag_query = f"{knowledge_gap}. {idea.get('khai_niem_kiem_tra', '')}. {idea.get('boi_canh', '')}"
        course_ctx, sources = self.ingestion.query_course_content_with_sources(rag_query, course_id)

        # Sinh lần đầu
        lop = self._generate(knowledge_gap, idea, course_ctx, lop_type, bloom_level, course_name)

        # Self-refine
        for i in range(n_refine):
            lop = self._refine(lop, knowledge_gap, course_ctx, lop_type, i + 1)

        return lop, sources

    def _generate(self, knowledge_gap, idea, course_ctx, lop_type, bloom_level, course_name="Khoa học Máy tính") -> dict:
        bloom_desc = BLOOM_LEVELS.get(bloom_level, bloom_level)
        lop_desc = LOP_TYPES.get(lop_type, lop_type)
        rag_block = ""
        if course_ctx and "Chưa có tài liệu" not in course_ctx and "Lỗi" not in course_ctx:
            rag_block = f"""
NỘI DUNG TÀI LIỆU KHÓA HỌC (từ PageIndex RAG - đã truy xuất từ nhiều tài liệu):
---
{course_ctx[:2000]}
---
QUAN TRỌNG: Hãy dùng ĐÚNG ký hiệu, thuật ngữ, và ví dụ từ tài liệu trên.
Không dùng ký hiệu hoặc ví dụ không có trong tài liệu khóa học.
"""

        if lop_type == "MCQ":
            return self._generate_mcq(knowledge_gap, idea, rag_block, bloom_desc, course_name)
        return self._generate_generic(knowledge_gap, idea, rag_block, lop_desc, bloom_desc, course_name)

    def _generate_mcq(self, knowledge_gap, idea, rag_block, bloom_desc, course_name="Khoa học Máy tính") -> dict:
        prompt = f"""Bạn là chuyên gia thiết kế câu hỏi trắc nghiệm (MCQ) cho khóa học {course_name}.
{rag_block}
LỖ HỔNG KIẾN THỨC CẦN ĐỊA CHỈ: "{knowledge_gap}"
Ý TƯỞNG ĐÃ CHỌN:
  - Tiêu đề: {idea.get('tieu_de', '')}
  - Bối cảnh: {idea.get('boi_canh', '')}
  - Khái niệm kiểm tra: {idea.get('khai_niem_kiem_tra', '')}
CẤP ĐỘ TƯ DUY: {bloom_desc}

NHIỆM VỤ: Thiết kế một MCQ chất lượng cao theo các yêu cầu sau:

YÊU CẦU PHẦN THÂN CÂU HỎI (stem):
- Mô tả một tình huống/bài toán CỤ THỂ, không hỏi lý thuyết trống
- Phải đặt sinh viên vào ngữ cảnh phải VẬN DỤNG kiến thức, không chỉ nhớ định nghĩa
- Rõ ràng, không mơ hồ, đủ thông tin để trả lời

YÊU CẦU CÁC ĐÁP ÁN (A, B, C, D):
- Đúng 1 đáp án CHÍNH XÁC theo tài liệu khóa học
- 3 đáp án SAI phải là những LẦM TƯỞNG THỰC TẾ mà sinh viên hay mắc phải
  (không được quá dễ loại trừ, không được vô lý)
- Tất cả đáp án có độ dài tương đương nhau

YÊU CẦU GIẢI THÍCH:
- Giải thích tại sao đáp án đúng là đúng (theo lý thuyết)
- Giải thích tại sao từng đáp án sai là sai (chỉ ra lầm tưởng cụ thể)
- Viết tiếng Việt, rõ ràng

TRẢ VỀ: Chỉ JSON hợp lệ, không markdown:
{{
  "lop_type": "MCQ",
  "cau_hoi": "Nội dung câu hỏi đầy đủ",
  "dap_an": {{
    "A": "Nội dung đáp án A",
    "B": "Nội dung đáp án B",
    "C": "Nội dung đáp án C",
    "D": "Nội dung đáp án D"
  }},
  "dap_an_dung": "A",
  "giai_thich": "Giải thích chi tiết tại sao đáp án đúng và tại sao các đáp án sai",
  "bloom_level": "{list(BLOOM_LEVELS.keys())[0]}"
}}

JSON:"""
        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "object")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        return {"lop_type": "MCQ", "cau_hoi": "Sinh thất bại", "dap_an": {}, "dap_an_dung": "", "giai_thich": ""}

    def _generate_generic(self, knowledge_gap, idea, rag_block, lop_desc, bloom_desc, course_name="Khoa học Máy tính") -> dict:
        prompt = f"""Bạn là chuyên gia thiết kế tài liệu học tập cho khóa học {course_name}.
{rag_block}
LỖ HỔNG KIẾN THỨC CẦN ĐỊA CHỈ: "{knowledge_gap}"
Ý TƯỞNG:
  - Bối cảnh: {idea.get('boi_canh', '')}
  - Khái niệm: {idea.get('khai_niem_kiem_tra', '')}
LOẠI TÀI LIỆU: {lop_desc}
CẤP ĐỘ TƯ DUY: {bloom_desc}

NHIỆM VỤ: Thiết kế {lop_desc} để giúp sinh viên khắc phục lỗ hổng trên.
Sử dụng đúng thuật ngữ, ký hiệu từ tài liệu khóa học.
Viết bằng tiếng Việt, rõ ràng, chi tiết.

TRẢ VỀ: Chỉ JSON hợp lệ:
{{
  "lop_type": "{list(LOP_TYPES.keys())[0]}",
  "tieu_de": "Tiêu đề ngắn gọn",
  "noi_dung": "Toàn bộ nội dung tài liệu học tập",
  "muc_tieu_hoc_tap": ["Mục tiêu 1", "Mục tiêu 2"],
  "bloom_level": "ap_dung"
}}

JSON:"""
        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "object")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        return {"lop_type": "exercise", "tieu_de": "Sinh thất bại", "noi_dung": "", "muc_tieu_hoc_tap": []}

    def _refine(self, lop: dict, knowledge_gap: str, course_ctx: str, lop_type: str, iteration: int) -> dict:
        lop_text = json.dumps(lop, ensure_ascii=False, indent=2)
        ctx_block = f"\nTÀI LIỆU THAM CHIẾU (PageIndex RAG):\n{course_ctx[:800]}\n" if course_ctx and "Chưa có" not in course_ctx else ""

        prompt = f"""Bạn đang TINH CHỈNH (Self-Refine lần {iteration}) một cơ hội học tập.
{ctx_block}
LỖ HỔNG KIẾN THỨC MỤC TIÊU: "{knowledge_gap}"

PHIÊN BẢN HIỆN TẠI:
{lop_text}

NHIỆM VỤ TINH CHỈNH:
Hãy phê bình phiên bản hiện tại theo các tiêu chí sau, sau đó tạo phiên bản CẢI THIỆN:

1. TÍNH CHÍNH XÁC: Nội dung có đúng về mặt học thuật không? Có khớp với tài liệu khóa học không?
2. ĐỘ KHÓ PHÙ HỢP: Câu hỏi/bài tập có đúng với cấp độ Bloom đã chỉ định không?
3. CHẤT LƯỢNG CÁC ĐÁP ÁN (nếu MCQ): Đáp án sai có đủ hấp dẫn, phản ánh đúng lầm tưởng của sinh viên không?
4. ĐỊA CHỈ LỖ HỔNG: Nội dung có trực tiếp nhắm vào đúng lỗ hổng, không phải chủ đề xung quanh?
5. NGÔN NGỮ & ĐỘ RÕ RÀNG: Câu hỏi có rõ ràng, không mơ hồ, viết đúng tiếng Việt không?

Tạo phiên bản cải thiện, giữ nguyên cấu trúc JSON, chỉ sửa những phần cần thiết.

TRẢ VỀ: Chỉ JSON hợp lệ với cấu trúc giống phiên bản hiện tại:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "object")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        return lop

    # ── Bước 4: Điều chỉnh độ khó ────────────────────────────────────────────

    def adjust_difficulty(self, lop: dict, difficulty: str, knowledge_gap: str) -> dict:
        diff_desc = DIFFICULTY.get(difficulty, difficulty)
        lop_text = json.dumps(lop, ensure_ascii=False, indent=2)

        prompt = f"""Bạn cần điều chỉnh độ khó của cơ hội học tập sau cho phù hợp với sinh viên.

ĐỘ KHÓ YÊU CẦU: {diff_desc}
LỖ HỔNG KIẾN THỨC: "{knowledge_gap}"

PHIÊN BẢN HIỆN TẠI:
{lop_text}

HƯỚNG DẪN ĐIỀU CHỈNH THEO ĐỘ KHÓ:
- Nếu ĐỘ KHÓ = Dễ:
  * Dùng ví dụ đơn giản, quen thuộc
  * Câu hỏi hỏi thẳng về định nghĩa hoặc áp dụng trực tiếp
  * Đáp án sai dễ loại trừ hơn
  * Không có trường hợp đặc biệt hay ngoại lệ

- Nếu ĐỘ KHÓ = Trung bình:
  * Tình huống có vài bước suy luận
  * Đáp án sai là những nhầm lẫn phổ biến
  * Có thể có một chi tiết nhỏ cần để ý

- Nếu ĐỘ KHÓ = Khó:
  * Tình huống phức tạp, nhiều yếu tố cần cân nhắc
  * Đáp án sai rất hấp dẫn, dễ chọn nếu không hiểu sâu
  * Có thể có trường hợp đặc biệt, edge case
  * Yêu cầu phân tích, tổng hợp thay vì chỉ áp dụng công thức

Giữ nguyên cấu trúc JSON, chỉ sửa nội dung cho phù hợp độ khó.
TRẢ VỀ: Chỉ JSON hợp lệ:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "object")
        if extracted:
            try:
                result = json.loads(extracted)
                result["do_kho"] = difficulty
                return result
            except json.JSONDecodeError:
                pass
        lop["do_kho"] = difficulty
        return lop

    # ── Bước 5: Đánh giá bằng AI guardrails ──────────────────────────────────

    # ── Bước 6: Xác định nguồn tham chiếu ───────────────────────────────────

    def attribute_sources(self, lop: dict, knowledge_gap: str, sources: list) -> dict:
        """
        Bước 6: Yêu cầu LLM xác định mục nào / file nào đã được dùng
        để tạo nội dung câu hỏi, dựa trên danh sách sources từ RAG.
        """
        if not sources:
            return {
                "used_sources": [],
                "summary": "Không có tài liệu tham chiếu được cung cấp khi sinh câu hỏi.",
            }

        lop_text = json.dumps(lop, ensure_ascii=False, indent=2)
        sources_block = "\n".join(
            f"{i+1}. [File: {s['file_name']}] — Mục: \"{s['section_title']}\" "
            f"(Trang {s['page_start']} - {s['page_end']})"
            for i, s in enumerate(sources)
        )

        prompt = f"""Bạn vừa tạo ra cơ hội học tập sau:
{lop_text[:1500]}

Các đoạn tài liệu khóa học đã được cung cấp cho bạn trước đó:
{sources_block}

NHIỆM VỤ:
Xác định những MỤC NÀO trong danh sách trên đã thực sự được dùng để xây dựng nội dung câu hỏi/tài liệu trên.
Giải thích ngắn gọn mỗi nguồn đóng góp thông tin gì vào câu hỏi.

TRẢ VỀ: Chỉ JSON hợp lệ, không giải thích thêm:
{{
  "used_sources": [
    {{
      "source_index": 1,
      "section_title": "Tên mục đã dùng",
      "doc_name": "Tên tài liệu",
      "file_name": "Tên file",
      "contribution": "Thông tin từ mục này đóng góp gì vào câu hỏi"
    }}
  ],
  "summary": "Tóm tắt 1 câu về nguồn tham chiếu chính đã được dùng"
}}

JSON:"""

        try:
            response = generate_with_retry(prompt)
            text = response.text.strip()
            extracted = _extract_json(text, "object")
            if extracted:
                result = json.loads(extracted)
                # Enrich với đầy đủ source metadata
                for used in result.get("used_sources", []):
                    idx = used.get("source_index", 1) - 1
                    if 0 <= idx < len(sources):
                        src = sources[idx]
                        used.setdefault("file_name", src.get("file_name", ""))
                        used.setdefault("doc_name", src.get("doc_name", ""))
                        used.setdefault("section_title", src.get("section_title", ""))
                        used["page_start"] = src.get("page_start")
                        used["page_end"] = src.get("page_end")
                        used["node_id"] = src.get("node_id", "")
                return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"attribute_sources thất bại: {e}")

        # Fallback: trả về tất cả sources đã dùng không có LLM attribution
        return {
            "used_sources": [
                {
                    "source_index": i + 1,
                    "section_title": s.get("section_title", ""),
                    "doc_name": s.get("doc_name", ""),
                    "file_name": s.get("file_name", ""),
                    "page_start": s.get("page_start"),
                    "page_end": s.get("page_end"),
                    "node_id": s.get("node_id", ""),
                    "contribution": "(Không xác định được)",
                }
                for i, s in enumerate(sources)
            ],
            "summary": "Nguồn tham chiếu được liệt kê tự động (LLM attribution thất bại).",
        }

    # ── Bước 5 (cũ): Đánh giá bằng AI guardrails ─────────────────────────────

    def evaluate(self, lop: dict, knowledge_gap: str, course_ctx: str = "") -> dict:
        lop_text = json.dumps(lop, ensure_ascii=False, indent=2)
        ctx_block = f"\nTÀI LIỆU KHÓA HỌC (tham chiếu):\n{course_ctx[:600]}\n" if course_ctx and "Chưa có" not in course_ctx else ""

        prompt = f"""Bạn là giảng viên đại học đang ĐÁNH GIÁ chất lượng một cơ hội học tập trước khi chia sẻ với sinh viên.
{ctx_block}
LỖ HỔNG KIẾN THỨC MỤC TIÊU: "{knowledge_gap}"

CƠ HỘI HỌC TẬP CẦN ĐÁNH GIÁ:
{lop_text}

HÃY ĐÁNH GIÁ THEO 4 TIÊU CHÍ SAU:

1. TÍNH CHÍNH XÁC (tinh_xac):
   - Nội dung có đúng về mặt học thuật không?
   - Đáp án đúng (nếu MCQ) có THỰC SỰ đúng không?
   - Đánh giá: "Tốt" / "Cần cải thiện" / "Sai"

2. ĐỘ SÂU NGỮ CẢNH (do_sau):
   - Nội dung có đủ ngữ cảnh để sinh viên học được điều gì đó không?
   - Giải thích có giúp sinh viên HIỂU nguyên nhân, không chỉ biết kết quả không?
   - Đánh giá: "Tốt" / "Cần cải thiện" / "Thiếu"

3. CHẤT LƯỢNG CÁC ĐÁP ÁN SAI (dap_an_sai) [CHỈ CHO MCQ]:
   - Các đáp án sai có phản ánh đúng những LẦM TƯỞNG PHỔ BIẾN của sinh viên không?
   - Có đáp án sai nào quá dễ loại trừ không? Có đáp án nào cũng đúng không?
   - Đánh giá: "Tốt" / "Cần cải thiện" / "Kém" / "Không áp dụng"

4. SỰ PHÙ HỢP VỚI LỖ HỔNG (phu_hop):
   - Nội dung có TRỰC TIẾP nhắm vào đúng lỗ hổng kiến thức không?
   - Hay chỉ hỏi về chủ đề xung quanh, không phải vấn đề cốt lõi?
   - Đánh giá: "Tốt" / "Cần cải thiện" / "Lệch hướng"

TRẢ VỀ: Chỉ JSON hợp lệ:
{{
  "tinh_xac": {{"danh_gia": "Tốt|Cần cải thiện|Sai", "nhan_xet": "Nhận xét cụ thể tiếng Việt"}},
  "do_sau": {{"danh_gia": "Tốt|Cần cải thiện|Thiếu", "nhan_xet": "Nhận xét cụ thể tiếng Việt"}},
  "dap_an_sai": {{"danh_gia": "Tốt|Cần cải thiện|Kém|Không áp dụng", "nhan_xet": "Nhận xét cụ thể"}},
  "phu_hop": {{"danh_gia": "Tốt|Cần cải thiện|Lệch hướng", "nhan_xet": "Nhận xét cụ thể"}},
  "tong_ket": "Tóm tắt 1-2 câu đánh giá chung",
  "de_xuat_chinh": "Đề xuất cải thiện quan trọng nhất (nếu có)"
}}

JSON:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "object")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        return {"tong_ket": "Đánh giá thất bại", "de_xuat_chinh": "Vui lòng xem xét thủ công"}

    def generate(
        self,
        knowledge_gap: str,
        sample_posts: list,
        course_id: str,
        lop_type: str = "MCQ",
        bloom_level: str = "ap_dung",
        difficulty: str = "trung_binh",
        course_name: str = "Khoa học Máy tính",
        n_refine: int = 2,
        num_questions: int = 1,
    ) -> dict:
        # RAG query context upfront (dùng cho brainstorm)
        course_ctx = self.ingestion.query_course_content(knowledge_gap, course_id)

        # Bước 1: Nảy sinh ý tưởng (CoT)
        ideas = self.brainstorm(
            knowledge_gap, sample_posts, lop_type, bloom_level, course_name,
            n_ideas=max(3, num_questions + 1), course_ctx=course_ctx
        )
        # Bước 2: Chọn ý tưởng tốt nhất
        best_ideas = self.select_best_ideas(ideas, knowledge_gap, num_questions)

        results = []
        for best in best_ideas:
            # Bước 3: Sinh + Self-Refine — trả về (lop, sources)
            lop, sources = self.generate_and_refine(
                knowledge_gap, best, course_id, lop_type, bloom_level, course_name, n_refine
            )
            # Bước 4: Điều chỉnh độ khó
            lop = self.adjust_difficulty(lop, difficulty, knowledge_gap)
            # Bước 5: Đánh giá AI Guardrails
            evaluation = self.evaluate(lop, knowledge_gap, course_ctx)
            # Bước 6: Xác định nguồn tham chiếu
            source_attribution = self.attribute_sources(lop, knowledge_gap, sources)

            results.append({
                "lop": lop,
                "evaluation": evaluation,
                "source_attribution": source_attribution,
                "metadata": {
                    "knowledge_gap": knowledge_gap,
                    "lop_type": lop_type,
                    "bloom_level": bloom_level,
                    "difficulty": difficulty,
                    "selected_idea": best,
                }
            })

        return {
            "lops": results,
            "metadata": {
                "knowledge_gap": knowledge_gap,
                "lop_type": lop_type,
                "bloom_level": bloom_level,
                "difficulty": difficulty
            }
        }
