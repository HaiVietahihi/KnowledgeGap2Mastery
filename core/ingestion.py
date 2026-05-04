"""

"""

import os
import sys
import uuid
import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Thêm PageIndex vào sys.path
PAGEINDEX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PageIndex")
if PAGEINDEX_DIR not in sys.path:
    sys.path.insert(0, PAGEINDEX_DIR)


def _extract_nodes_from_structure(structure, nodes=None, index_counter=None, parent_id=None, level=0):
    """
    Đệ quy trích xuất các node từ cây cấu trúc PageIndex.
    Xây dựng quan hệ cha con thông qua parent_id.
    """
    if nodes is None:
        nodes = []
    if index_counter is None:
        index_counter = [0]

    if isinstance(structure, dict):
        node_id = structure.get("node_id")
        if not node_id:
            node_id = f"node-{uuid.uuid4().hex[:8]}"

        node = {
            "node_id": node_id,
            "parent_node_id": parent_id,
            "level": level,
            "chunk_index": index_counter[0],
            "title": structure.get("title", ""),
            "content": structure.get("text", ""),
            "summary": structure.get("summary", ""),
            "page_start": structure.get("start_index"),
            "page_end": structure.get("end_index"),
        }
        # Chỉ thêm node nếu có nội dung
        if node["content"] or node["summary"] or node["title"]:
            nodes.append(node)
            index_counter[0] += 1

        # Xử lý child nodes
        if "nodes" in structure:
            _extract_nodes_from_structure(structure["nodes"], nodes, index_counter, node_id, level + 1)
        elif "sub_nodes" in structure:
            _extract_nodes_from_structure(structure["sub_nodes"], nodes, index_counter, node_id, level + 1)

    elif isinstance(structure, list):
        for item in structure:
            _extract_nodes_from_structure(item, nodes, index_counter, parent_id, level)

    return nodes


class CourseIngestion:
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

    # ── Upload & Process PDF bằng PageIndex local ────────────────────────────

    def upload_document(
        self,
        file_path: str,
        course_id: str,
        doc_type: str = "lecture_notes",
        doc_name: Optional[str] = None,
        app=None,
    ) -> dict:
        """
        Upload một file PDF, xử lý bằng PageIndex local, lưu kết quả vào DB.
        Trả về dict metadata của document.
        """
        from database.repository import DocumentRepo, DocumentNodeRepo

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

        doc_name = doc_name or path.stem
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"

        # Tạo record trong DB với status=processing
        DocumentRepo.create(doc_id, course_id, doc_name, doc_type, path.name)

        # Xử lý PDF bằng PageIndex local trong background thread
        def process_pdf():
            try:
                nodes = []
                
                # Thử xử lý bằng PageIndex local
                try:
                    from pageindex import page_index
                    
                    logger.info(f"Bắt đầu xử lý PDF bằng PageIndex local: {path.name}")
                    
                    result = page_index(
                        str(path),
                        model=os.environ.get("PAGEINDEX_MODEL", "gpt-oss:20b"),
                        if_add_node_id="yes",
                        if_add_node_summary="yes",
                        if_add_doc_description="no",
                        if_add_node_text="yes",
                    )

                    structure = result.get("structure", [])
                    nodes = _extract_nodes_from_structure(structure)
                    logger.info(f"PageIndex trích xuất được {len(nodes)} nodes")
                    
                except Exception as pi_error:
                    logger.warning(f"PageIndex local thất bại ({pi_error}), dùng PyPDF2 fallback...")
                
                # Fallback: nếu PageIndex thất bại hoặc không trích xuất được node
                if not nodes:
                    logger.info(f"Sử dụng PyPDF2 fallback để trích xuất text từ {path.name}")
                    nodes = self._fallback_extract(path)

                # Đếm số trang
                try:
                    import PyPDF2
                    with open(path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        page_count = len(reader.pages)
                except Exception:
                    page_count = 0

                desc = f"Đã xử lý {page_count} trang, {len(nodes)} nodes"
                
                # Lưu nodes vào DB (cần app context cho SQLAlchemy)
                if app:
                    with app.app_context():
                        DocumentNodeRepo.create_bulk(doc_id, nodes)
                        DocumentRepo.update_status(
                            doc_id, "completed",
                            page_count=page_count,
                            description=desc
                        )
                else:
                    DocumentNodeRepo.create_bulk(doc_id, nodes)
                    DocumentRepo.update_status(
                        doc_id, "completed",
                        page_count=page_count,
                        description=desc
                    )

                logger.info(f"Xử lý hoàn tất: {doc_name} — {len(nodes)} nodes, {page_count} trang")

            except Exception as e:
                logger.error(f"Lỗi xử lý PDF {path.name}: {e}")
                try:
                    if app:
                        with app.app_context():
                            DocumentRepo.update_status(doc_id, "error", error_message=str(e))
                    else:
                        DocumentRepo.update_status(doc_id, "error", error_message=str(e))
                except Exception:
                    pass

        # Chạy trong background thread
        thread = threading.Thread(target=process_pdf, daemon=True)
        thread.start()

        return {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "doc_type": doc_type,
            "file_name": path.name,
            "course_id": course_id,
            "status": "processing",
        }

    def _fallback_extract(self, path: Path) -> list:
        """Fallback: trích xuất text thô từ PDF bằng PyPDF2 nếu PageIndex structure rỗng."""
        import PyPDF2
        nodes = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    nodes.append({
                        "node_id": f"node-{uuid.uuid4().hex[:8]}",
                        "parent_node_id": None,
                        "level": 0,
                        "chunk_index": i,
                        "title": f"Trang {i+1}",
                        "content": text,
                        "summary": "",
                        "page_start": i + 1,
                        "page_end": i + 1,
                    })
        return nodes

    # ── RAG: Truy vấn nội dung khóa học từ Database ──────────────────────────

    def _build_toc_context(self, course_id: str, max_depth: int = 3, max_tokens: int = 20000) -> str:
        """Tái tạo cây mục lục (ToC) JSON cho LLM từ cơ sở dữ liệu để chọn node."""
        from database.repository import DocumentNodeRepo
        all_nodes = DocumentNodeRepo.get_all_by_course(course_id)
        if not all_nodes:
            return ""

        toc_list = []
        estimated_tokens = 0
        
        for node in all_nodes:
            if node.level <= max_depth:
                node_info = {
                    "node_id": node.node_id,
                    "title": node.title,
                    "summary": node.summary
                }
                info_str = json.dumps(node_info, ensure_ascii=False)
                # Đếm token xấp xỉ (~4 chars = 1 token)
                estimated_tokens += len(info_str) // 4
                if estimated_tokens > max_tokens:
                    logger.warning("Đã chạm giới hạn max_tokens khi build ToC")
                    break
                toc_list.append(node_info)
                
        return json.dumps(toc_list, ensure_ascii=False, indent=2)

    def _query_core(
        self,
        query: str,
        course_id: str,
    ) -> tuple:
        """
        Lõi RAG 2 bước, trả về (content_str, sources_list).
        sources_list: list of dict {node_id, section_title, doc_name, file_name, page_start, page_end}
        """
        from database.repository import DocumentNodeRepo, DocumentRepo
        from core.utils import generate_with_retry

        toc_json = self._build_toc_context(course_id, max_depth=3, max_tokens=20000)
        if not toc_json:
            return "Chưa có tài liệu nào được nạp cho khóa học này.", []

        # Step 1: LLM chọn node_id
        prompt_select = f"""Bạn là hệ thống Reasoning-based RAG. Bạn cần đọc Mục lục (ToC) của tài liệu và quyết định xem để trả lời câu hỏi: "{query}", bạn cần tham khảo NỘI DUNG của những phần nào?

MỤC LỤC TÀI LIỆU (JSON):
{toc_json}

TRẢ VỀ: Chỉ trả về MỘT mảng JSON chứa các `node_id` cần thiết nhất (tối đa 5 node_id), KHÔNG GIẢI THÍCH CHỮ NÀO BÊN NGOÀI MẢNG.
Ví dụ: ["001", "005"]
JSON:"""

        selected_ids = []
        try:
            resp = generate_with_retry(prompt_select)
            text = resp.text.strip()
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1:
                selected_ids = json.loads(text[start:end+1])
        except Exception as e:
            logger.error(f"Lỗi khi LLM chọn node: {e}")

        # Fallback lấy node đầu nếu LLM không chọn được
        all_nodes = DocumentNodeRepo.get_all_by_course(course_id)
        if not selected_ids or not isinstance(selected_ids, list):
            selected_ids = [n.node_id for n in all_nodes[:3]]

        # Step 2: Lấy content đầy đủ + thu thập source info
        nodes = DocumentNodeRepo.get_nodes_by_ids(course_id, selected_ids)
        if not nodes:
            nodes = all_nodes[:3]

        parts = []
        sources = []
        doc_cache = {}  # tránh query DB nhiều lần cho cùng document

        for node in nodes:
            header = f"[{node.title}] (Node ID: {node.node_id})" if node.title else f"(Node ID: {node.node_id})"
            body = node.content or node.summary or ""
            if body:
                parts.append(f"{header}\n{body}")

            # Lấy thông tin tài liệu (document) từ document_id
            doc_id = getattr(node, 'document_id', None)
            doc_name = "Không rõ"
            file_name = "Không rõ"
            if doc_id:
                if doc_id not in doc_cache:
                    doc_cache[doc_id] = DocumentRepo.get(doc_id)
                doc = doc_cache[doc_id]
                if doc:
                    doc_name = doc.doc_name
                    file_name = doc.file_name

            sources.append({
                "node_id": node.node_id,
                "section_title": node.title or "(Không có tiêu đề)",
                "doc_name": doc_name,
                "file_name": file_name,
                "page_start": getattr(node, 'page_start', None),
                "page_end": getattr(node, 'page_end', None),
            })

        combined = "\n\n---\n\n".join(parts)
        if len(combined) > 15000:
            combined = combined[:15000] + "\n...(đã cắt bớt)"

        return combined, sources

    def query_course_content(
        self,
        query: str,
        course_id: str,
        doc_types: Optional[list] = None,
    ) -> str:
        """
        Quy trình 2-Step Reasoning-based RAG — trả về nội dung dạng chuỗi.
        (Backward compatible — dùng cho discovery.py và brainstorm)
        """
        content, _ = self._query_core(query, course_id)
        return content

    def query_course_content_with_sources(
        self,
        query: str,
        course_id: str,
        doc_types: Optional[list] = None,
    ) -> tuple:
        """
        Trả về (content_str, sources_list) — dùng cho generation pipeline
        để truy xuất nguồn tham chiếu mà LLM đã sử dụng.
        """
        return self._query_core(query, course_id)

    # ── Document management ───────────────────────────────────────────────────

    def list_documents(self, course_id: str) -> list:
        """Liệt kê tài liệu của khóa học từ DB."""
        from database.repository import DocumentRepo
        docs = DocumentRepo.list_by_course(course_id)
        return [
            {
                "doc_id": doc.id,
                "doc_name": doc.doc_name,
                "doc_type": doc.doc_type,
                "file_name": doc.file_name,
                "course_id": doc.course_id,
                "status": doc.status,
                "page_count": doc.page_count,
                "description": doc.description,
                "uploaded_at": doc.created_at.strftime("%Y-%m-%dT%H:%M:%S") if doc.created_at else "",
                "error_message": doc.error_message,
            }
            for doc in docs
        ]

    def delete_document(self, doc_id: str, course_id: str = None) -> bool:
        """Xóa tài liệu khỏi DB."""
        from database.repository import DocumentRepo
        return DocumentRepo.delete(doc_id)

    def get_document(self, doc_id: str) -> Optional[dict]:
        """Lấy thông tin tài liệu."""
        from database.repository import DocumentRepo
        doc = DocumentRepo.get(doc_id)
        if not doc:
            return None
        return {
            "doc_id": doc.id,
            "doc_name": doc.doc_name,
            "doc_type": doc.doc_type,
            "status": doc.status,
            "page_count": doc.page_count,
        }

    def check_document_status(self, doc_id: str) -> dict:
        """Kiểm tra trạng thái xử lý tài liệu."""
        from database.repository import DocumentRepo
        doc = DocumentRepo.get(doc_id)
        if not doc:
            return {"status": "not_found"}
        return {
            "doc_id": doc.id,
            "status": doc.status,
            "page_count": doc.page_count,
            "error_message": doc.error_message,
        }

    def get_course_summary(self, course_id: str) -> str:
        docs = self.list_documents(course_id)
        if not docs:
            return "Chưa có tài liệu nào."
        lines = [f"Khóa học '{course_id}' có {len(docs)} tài liệu:"]
        for d in docs:
            pages = f"{d.get('page_count', '?')} trang" if d.get("page_count") else ""
            lines.append(f"  • [{d['doc_type']}] {d['doc_name']} {pages} — {d['status']}")
        return "\n".join(lines)
