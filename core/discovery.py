"""
KG2M - core/discovery.py
Phát hiện lỗ hổng kiến thức từ câu hỏi của sinh viên.
Toàn bộ prompt viết bằng tiếng Việt, chi tiết để hệ thống hiểu chính xác.
"""

import json
import logging
from core.ingestion import CourseIngestion
from core.utils import generate_with_retry

logger = logging.getLogger(__name__)


def _extract_json(text: str, target: str = "object") -> str | None:
    """
    Trích xuất JSON object ({...}) hoặc array ([...]) từ text
    bằng balanced bracket counting — xử lý đúng JSON lồng nhau.
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


class KnowledgeGapDiscovery:
    def __init__(
        self,
        gemini_api_key: str,
        ingestion: CourseIngestion,
        model_name: str = "gpt-oss:20b",
    ):
        self.model_name = model_name
        self.ingestion = ingestion

    # ── Bước 1: Xác định lỗ hổng trong từng bài đăng (BATCH) ────────────────

    def identify_gaps_in_batch(
        self, posts: list, course_context: str = "", course_name: str = ""
    ) -> list:
        """
        Xác định lỗ hổng kiến thức cho nhiều bài đăng cùng lúc.
        Không cần sleep ở đây vì generate_with_retry đã xử lý rate limit.
        """
        if not posts:
            return []

        context_block = ""
        if course_context and "Chưa có tài liệu" not in course_context:
            context_block = f"""
NỘI DUNG TÀI LIỆU KHÓA HỌC LIÊN QUAN (truy xuất từ RAG):
---
{course_context[:1500]}
---
Hãy dùng nội dung tài liệu trên để hiểu đúng hơn ngữ cảnh học thuật của câu hỏi.
"""

        course_desc = f" môn {course_name}" if course_name else ""
        posts_block = "\n\n".join(
            f"BÀI #{i+1}:\n{post}" for i, post in enumerate(posts)
        )

        prompt = f"""Bạn là một giảng viên đại học giàu kinh nghiệm đang phân tích các câu hỏi của sinh viên{course_desc} trên hệ thống học tập.

NHIỆM VỤ CỦA BẠN:
Đọc kỹ {len(posts)} bài đăng dưới đây và phân tích để tìm ra TOÀN BỘ các lỗ hổng kiến thức (có thể có nhiều lỗ hổng trong 1 bài đăng) mà sinh viên đang gặp phải CHO TỪNG BÀI.
{context_block}
CÁC BÀI ĐĂNG CỦA SINH VIÊN:
---
{posts_block}
---

QUY TẮC PHÂN TÍCH CHO MỖI BÀI:
1. Nếu bài đăng là câu hỏi hành chính (hạn nộp bài, lịch học, kỹ thuật đăng nhập...) → Mảng rỗng hoặc ghi "Không có lỗ hổng kiến thức".
2. Nếu sinh viên chỉ chào hỏi hoặc cảm ơn → Mảng rỗng hoặc ghi "Không có lỗ hổng kiến thức".
3. CHÚ Ý QUAN TRỌNG: Nếu bài đăng hỏi về một kiến thức HOÀN TOÀN KHÔNG CÓ trong NỘI DUNG TÀI LIỆU KHÓA HỌC LIÊN QUAN (kiến thức ngoài luồng, không thuộc phạm vi môn học), hãy ghi "Không có lỗ hổng kiến thức".
4. Nếu bài đăng chứa nhiều câu hỏi về nhiều khía cạnh khác nhau thuộc môn học, hãy liệt kê tách biệt từng lỗ hổng kiến thức. Hãy mô tả KHÁI NIỆM cụ thể mà sinh viên chưa hiểu. Lỗ hổng cần là một câu duy nhất.
5. Viết bằng tiếng Việt.
6. Nếu KHÔNG có lỗ hổng: mảng kết quả của bài đó chứa đúng 1 chuỗi "Không có lỗ hổng kiến thức".

ĐẦU RA (bắt buộc):
Hãy trả về một MẢNG LỚN chứa các MẢNG NHỎ, mỗi mảng con tương ứng với danh sách lỗ hổng của 1 bài đăng theo thứ tự.
Ví dụ:
[
  [
    "Chưa hiểu cách tìm số cụm K cho thuật toán K-means",
    "Chưa biết cách vẽ đồ thị bằng gói quantmod trong ngôn ngữ R"
  ],
  [
    "Không có lỗ hổng kiến thức"
  ]
]

JSON:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "array")
        if extracted:
            try:
                gaps_nested_list = json.loads(extracted)
                if len(gaps_nested_list) < len(posts):
                    gaps_nested_list.extend(
                        [["Không có lỗ hổng kiến thức"]] * (len(posts) - len(gaps_nested_list))
                    )
                # flatten the nested list but return flat list
                flat_gaps = []
                for item in gaps_nested_list[:len(posts)]:
                    if isinstance(item, list):
                        flat_gaps.extend(item)
                    elif isinstance(item, str):
                        flat_gaps.append(item)
                return flat_gaps
            except json.JSONDecodeError:
                logger.warning("JSON decode error in identify_gaps_in_batch, using fallback.")

        return ["Không thể phân tích."] * len(posts)

    # ── Bước 2: Gộp nhóm các lỗ hổng thành danh mục ────────────────────────

    def accumulate_gaps(self, gaps: list, batch_size: int = 15) -> list:
        """
        Hướng dẫn 2 (Algorithm 1): Gộp các lỗ hổng đơn lẻ thành danh mục tổng quát.
        Rate limiting được xử lý hoàn toàn bởi generate_with_retry — KHÔNG dùng sleep thủ công.
        Số danh mục do mô hình AI tự quyết định.
        """
        valid = [g for g in gaps if g and isinstance(g, str) and "Không có" not in g and "Không thể" not in g]
        if not valid:
            return []

        all_categories = []
        for i in range(0, len(valid), batch_size):
            batch = valid[i : i + batch_size]
            cats = self._group_batch(batch)
            all_categories.extend(cats)
            # KHÔNG cần sleep — generate_with_retry đã tự rate-limit

        # Gộp lần cuối nếu còn quá nhiều danh mục (phân tán từ nhiều batch)
        if len(all_categories) > 15:
            all_categories = self._group_batch(all_categories)

        # Loại trùng lặp, giữ thứ tự
        seen = set()
        result = []
        for c in all_categories:
            if c not in seen:
                seen.add(c)
                result.append(c)
        return result

    def _group_batch(self, gaps: list) -> list:
        items = "\n".join(f"- {g}" for g in gaps)
        prompt = f"""Bạn là chuyên gia sư phạm đang phân loại các lỗ hổng kiến thức của sinh viên.

DANH SÁCH LỖ HỔNG CẦN PHÂN NHÓM:
{items}

NHIỆM VỤ:
Gộp các lỗ hổng trên thành các DANH MỤC TỔNG QUÁT.
Bạn hãy TỰ QUYẾT ĐỊNH số lượng danh mục phù hợp nhất dựa trên nội dung các lỗ hổng.
Nếu các lỗ hổng rất đa dạng, có thể tạo nhiều danh mục. Nếu các lỗ hổng tương tự nhau, gộp thành ít danh mục hơn.

YÊU CẦU CHO MỖI DANH MỤC:
1. Phải bao quát được nhiều lỗ hổng tương tự nhau trong danh sách trên.
2. Tên danh mục phải mô tả rõ KHÁI NIỆM học thuật cụ thể, không chung chung.
   - VÍ DỤ SAI: "Vấn đề về thuật toán"
   - VÍ DỤ ĐÚNG: "Chưa hiểu cách phân tích độ phức tạp thời gian Big-O của vòng lặp lồng nhau"
3. Viết bằng tiếng Việt.
4. Mỗi danh mục là một chuỗi ngắn gọn (dưới 20 từ).

TRẢ VỀ: Chỉ một mảng JSON hợp lệ, không giải thích thêm.
Ví dụ định dạng: ["Danh mục A", "Danh mục B", "Danh mục C"]

JSON:"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        extracted = _extract_json(text, "array")
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                logger.warning("JSON decode error in _group_batch, falling back to line parsing.")

        return [
            line.strip('- "[]').strip()
            for line in text.split("\n")
            if line.strip('- "[]').strip()
        ]

    # ── Bước 3: Phân loại bài đăng vào danh mục ─────────────────────────────

    def classify_posts(self, posts: list, categories: list) -> list:
        """
        Hướng dẫn 4 (Algorithm 1): Phân loại từng bài đăng vào 0, 1 hoặc nhiều danh mục.
        """
        cat_list = "\n".join(f"{i+1}. {c}" for i, c in enumerate(categories))
        classified = []
        batch_size = 15

        for i in range(0, len(posts), batch_size):
            batch = posts[i : i + batch_size]
            posts_block = "\n\n".join(
                f"BÀI ĐĂNG #{j+1}:\n{p[:400]}" for j, p in enumerate(batch)
            )
            prompt = f"""Bạn là giảng viên đang phân loại các câu hỏi sinh viên theo danh mục lỗ hổng kiến thức.

DANH MỤC LỖ HỔNG KIẾN THỨC:
{cat_list}

CÁC BÀI ĐĂNG CẦN PHÂN LOẠI:
{posts_block}

NHIỆM VỤ:
Với mỗi bài đăng, xác định bài đăng đó thuộc danh mục nào (có thể thuộc 0, 1, hoặc nhiều danh mục).

QUY TẮC PHÂN LOẠI:
1. Chỉ gán danh mục nếu bài đăng THỰC SỰ thể hiện lỗ hổng kiến thức đó.
2. Nếu bài đăng không có lỗ hổng kiến thức nào (hành chính, chào hỏi, không thuộc phạm vi môn học...) → "categories" để rỗng [], "has_gap": false, và cung cấp "reason" giải thích tại sao câu hỏi không được đưa vào phân tích lỗ hổng.
3. Gán TÊN DANH MỤC CHÍNH XÁC như trong danh sách trên (không viết tắt, không sửa).

TRẢ VỀ: Chỉ một mảng JSON hợp lệ theo định dạng sau, không giải thích:
[
  {{"post_index": 1, "categories": ["Tên danh mục chính xác"], "has_gap": true, "reason": ""}},
  {{"post_index": 2, "categories": [], "has_gap": false, "reason": "Câu hỏi hỏi về lịch thi, không liên quan đến chuyên môn môn học"}}
]

JSON:"""

            response = generate_with_retry(prompt)
            text = response.text.strip()
            extracted = _extract_json(text, "array")
            if extracted:
                try:
                    results = json.loads(extracted)
                    for j, r in enumerate(results):
                        if j < len(batch):
                            classified.append(
                                {
                                    "post": batch[j],
                                    "categories": r.get("categories", []),
                                    "has_gap": r.get("has_gap", False),
                                    "reason": r.get("reason", ""),
                                }
                            )
                    continue
                except json.JSONDecodeError:
                    logger.warning(f"JSON decode error in classify_posts batch {i}, using fallback.")

            for p in batch:
                classified.append({"post": p, "categories": [], "has_gap": False, "reason": "Lỗi phân tích"})

        return classified

    # ── Tính coverage & cohesion ──────────────────────────────────────────────

    def compute_metrics(self, classified_posts: list, categories: list) -> list:
        """
        Bước 3 (KG2M): Tính coverage (số bài đăng) và cohesion (mức độ nhất quán).
        """
        cat_posts = {c: [] for c in categories}
        for item in classified_posts:
            for cat in item.get("categories", []):
                if cat in cat_posts:
                    cat_posts[cat].append(item["post"][:300])

        results = []
        for cat in categories:
            posts = cat_posts[cat]
            cohesion = (
                self._assess_cohesion(cat, posts) if len(posts) >= 2 else "Cao"
            )
            results.append(
                {
                    "knowledge_gap": cat,
                    "coverage": len(posts),
                    "cohesion": cohesion,
                    "posts": posts,
                }
            )
            # KHÔNG cần sleep — generate_with_retry đã xử lý

        results.sort(key=lambda x: x["coverage"], reverse=True)
        return results

    def _assess_cohesion(self, category: str, posts: list) -> str:
        sample = posts[:5]
        items = "\n".join(f"- {p[:200]}" for p in sample)
        prompt = f"""Bạn đang đánh giá mức độ NHẤT QUÁN của các bài đăng sinh viên so với một danh mục lỗ hổng kiến thức.

DANH MỤC: "{category}"

CÁC BÀI ĐĂNG MẪU:
{items}

NHIỆM VỤ:
Đánh giá xem các bài đăng này có thực sự tập trung vào đúng vấn đề của danh mục hay không.

THANG ĐÁNH GIÁ:
- Cao: Tất cả bài đăng đều hỏi về ĐÚNG khái niệm của danh mục, rất cụ thể và nhất quán.
- Trung bình: Các bài đăng có liên quan đến danh mục nhưng hỏi về nhiều khía cạnh khác nhau.
- Thấp: Các bài đăng khá đa dạng, chỉ liên quan xa đến danh mục, danh mục quá rộng.

TRẢ VỀ: Chỉ MỘT từ duy nhất: Cao, Trung bình, hoặc Thấp"""

        response = generate_with_retry(prompt)
        text = response.text.strip()
        if "Cao" in text:
            return "Cao"
        if "Thấp" in text:
            return "Thấp"
        return "Trung bình"

    # ── Pipeline đầy đủ ───────────────────────────────────────────────────────

    def discover(
        self,
        posts: list,
        course_id: str,
        course_name: str = "",
    ) -> dict:
        """
        Chạy toàn bộ pipeline phát hiện lỗ hổng kiến thức (Steps 2-3).
        Luôn sử dụng RAG. Số danh mục do mô hình AI tự quyết định.

        LƯU Ý VỀ RATE LIMIT:
        - Mọi API call đều đi qua generate_with_retry (core/utils.py)
        - generate_with_retry tự động:
            + Đợi tối thiểu 5 giây giữa các request (15 RPM free tier)
            + Retry với exponential backoff khi gặp lỗi 429/503
        - KHÔNG dùng time.sleep() thủ công trong file này nữa
        """
        logger.info(f"Starting knowledge gap discovery for course '{course_id}' "
                    f"with {len(posts)} posts (always RAG)")

        # ── Lấy context RAG (chỉ 1 lần cho toàn bộ pipeline) ────────────────
        ctx = ""
        if posts:
            # Query RAG với sample posts để lấy context học thuật chung
            common_query = "\n".join(p[:100] for p in posts[:3])
            ctx = self.ingestion.query_course_content(common_query, course_id)
            logger.info("RAG context retrieved successfully.")

        # ── Bước 1: Xác định lỗ hổng từng bài theo batch ────────────────────
        individual_gaps = []
        batch_size = 15

        for i in range(0, len(posts), batch_size):
            batch_posts = posts[i : i + batch_size]
            logger.info(f"Identifying gaps: batch {i//batch_size + 1} "
                        f"({len(batch_posts)} posts)")
            gaps = self.identify_gaps_in_batch(batch_posts, ctx, course_name)
            individual_gaps.extend(gaps)

        logger.info(f"Individual gaps identified: {len(individual_gaps)}")

        # ── Bước 2: Gộp thành danh mục (số lượng do mô hình quyết định) ─────
        categories = self.accumulate_gaps(individual_gaps)

        logger.info(f"Categories discovered ({len(categories)}): {categories}")

        # ── Bước 3: Phân loại bài đăng vào danh mục ─────────────────────────
        classified = self.classify_posts(posts, categories)

        # ── Bước 4: Tính metrics (coverage & cohesion) ───────────────────────
        gaps_result = self.compute_metrics(classified, categories)

        logger.info("Knowledge gap discovery completed.")

        return {
            "categories": categories,
            "classified_posts": classified,
            "knowledge_gaps": gaps_result,
        }
