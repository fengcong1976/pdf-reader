"""PDF 文档管理模块 - 封装 PyMuPDF 提供文档操作 API"""

import pymupdf
from typing import Optional, List, Tuple


class PDFDocument:
    """PDF 文档封装类，提供文档加载、渲染、搜索等基础操作"""

    def __init__(self):
        self._doc: Optional[pymupdf.Document] = None
        self._file_path: str = ""

    # ── 文档加载与保存 ──────────────────────────────────────────

    def load(self, file_path: str) -> bool:
        """加载 PDF 文件，返回是否成功"""
        try:
            self._doc = pymupdf.open(file_path)
            self._file_path = file_path
            return True
        except Exception:
            self._doc = None
            self._file_path = ""
            return False

    def close(self):
        """关闭文档"""
        if self._doc:
            self._doc.close()
            self._doc = None
            self._file_path = ""

    def save(self, file_path: str, encryption: Optional[str] = None, password: str = "") -> bool:
        """保存文档，可选加密"""
        if not self._doc:
            return False
        try:
            if encryption and password:
                # 使用 PyMuPDF 的加密保存
                perm = (
                    pymupdf.PDF_PERM_PRINT
                    | pymupdf.PDF_PERM_COPY
                    | pymupdf.PDF_PERM_ANNOTATE
                )
                crypt_meth = (
                    pymupdf.PDF_ENCRYPT_AES_256 if encryption == "aes256"
                    else pymupdf.PDF_ENCRYPT_RC4_128
                )
                self._doc.save(
                    file_path,
                    encryption=crypt_meth,
                    user_pw=password,
                    owner_pw=password,
                    encryption_method=encryption,
                    permissions=perm,
                )
            else:
                self._doc.save(file_path)
            return True
        except Exception:
            return False

    # ── 属性查询 ────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self._doc is not None

    @property
    def file_path(self) -> str:
        return self._file_path

    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    @property
    def metadata(self) -> dict:
        if not self._doc:
            return {}
        return self._doc.metadata or {}

    def is_encrypted(self) -> bool:
        return self._doc.is_encrypted if self._doc else False

    def authenticate(self, password: str) -> bool:
        """用密码解锁加密文档"""
        if not self._doc:
            return False
        return self._doc.authenticate(password) > 0

    # ── 页面渲染 ────────────────────────────────────────────────

    def get_page_pixmap(self, page_num: int, zoom: float = 1.0, rotation: int = 0) -> Optional[pymupdf.Pixmap]:
        """渲染指定页面为 Pixmap（rotation 参数保留但由 Qt 层面实现旋转）"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return None
        try:
            page = self._doc[page_num]
            mat = pymupdf.Matrix(zoom, zoom)
            return page.get_pixmap(matrix=mat, alpha=False)
        except Exception:
            return None

    def get_page_size(self, page_num: int) -> Tuple[float, float]:
        """获取页面显示尺寸 (width, height)（已包含 PDF 自带旋转）"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return (0, 0)
        # PyMuPDF 的 page.rect 已是应用 rotation 后的显示矩形，
        # 与 get_pixmap 输出图像尺寸一致，无需再手动互换宽高
        rect = self._doc[page_num].rect
        return (rect.width, rect.height)

    def get_page_text(self, page_num: int) -> str:
        """获取页面文本内容"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return ""
        try:
            return self._doc[page_num].get_text("text")
        except Exception:
            return ""

    def get_text_in_rect(self, page_num: int, rect) -> str:
        """提取页面指定区域内的文字层文本

        rect 为 (x0, y0, x1, y1)，zoom=1 渲染坐标（应用 PDF 自带旋转后的
        显示空间）。区域无文字层（扫描图片）时返回空串。
        """
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return ""
        try:
            clip = pymupdf.Rect(*rect)
            return self._doc[page_num].get_text("text", clip=clip).strip()
        except Exception:
            return ""

    def get_all_text(self) -> str:
        """获取全文"""
        if not self._doc:
            return ""
        return "\n".join(
            self._doc[i].get_text("text") for i in range(self.page_count)
        )

    # ── 搜索 ────────────────────────────────────────────────────

    def search_text(self, query: str, case_sensitive: bool = False) -> List[Tuple[int, List[pymupdf.Rect]]]:
        """全文搜索，返回 [(page_num, [rect, ...]), ...]"""
        if not self._doc or not query:
            return []
        results = []
        flags = 0 if case_sensitive else pymupdf.TEXT_DEHYPHENATE
        for i in range(self.page_count):
            rects = self._doc[i].search_for(query, quads=False, flags=flags)
            if rects:
                results.append((i, rects))
        return results

    # ── 目录大纲 ────────────────────────────────────────────────

    def get_outline(self) -> List[dict]:
        """获取 PDF 目录大纲，返回结构化的树形列表"""
        if not self._doc:
            return []
        toc = self._doc.get_toc()
        if not toc:
            return []
        # 构建树形结构
        root = []
        stack = [(0, root)]  # (level, children_list)
        for level, title, page in toc:
            node = {"title": title, "page": page - 1, "children": []}  # page 转为 0-based
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack[-1][1].append(node)
            stack.append((level, node["children"]))
        return root

    # ── 注释 ────────────────────────────────────────────────────

    def add_highlight(self, page_num: int, rects: List[pymupdf.Rect]) -> bool:
        """添加高亮注释"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return False
        try:
            page = self._doc[page_num]
            for rect in rects:
                page.add_highlight_annot(rect)
            return True
        except Exception:
            return False

    def add_text_annot(self, page_num: int, point: pymupdf.Point, text: str) -> bool:
        """添加文本注释（便签）"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return False
        try:
            page = self._doc[page_num]
            page.add_text_annot(point, text)
            return True
        except Exception:
            return False

    def get_annotations(self, page_num: int) -> List[dict]:
        """获取页面上的所有注释"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return []
        annos = []
        try:
            page = self._doc[page_num]
            for annot in page.annots():
                annos.append({
                    "type": annot.type[0],
                    "type_name": annot.type[1],
                    "rect": annot.rect,
                    "info": annot.info,
                })
        except Exception:
            pass
        return annos

    def clear_annotations(self, page_num: int) -> bool:
        """清除页面所有注释"""
        if not self._doc or page_num < 0 or page_num >= self.page_count:
            return False
        try:
            page = self._doc[page_num]
            for annot in page.annots():
                annot.delete()
            return True
        except Exception:
            return False

    # ── 页面操作（高级功能）──────────────────────────────────────

    def extract_page_range(self, start: int, end: int, output_path: str) -> bool:
        """提取页面范围并保存为新 PDF (0-based, 含 end)"""
        if not self._doc:
            return False
        try:
            new_doc = pymupdf.open()
            new_doc.insert_pdf(self._doc, from_page=start, to_page=end)
            new_doc.save(output_path)
            new_doc.close()
            return True
        except Exception:
            return False

    def merge(self, file_paths: List[str], output_path: str) -> bool:
        """合并多个 PDF 文件"""
        try:
            new_doc = pymupdf.open()
            for fp in file_paths:
                src = pymupdf.open(fp)
                new_doc.insert_pdf(src)
                src.close()
            new_doc.save(output_path)
            new_doc.close()
            return True
        except Exception:
            return False

    def get_raw_document(self) -> Optional[pymupdf.Document]:
        """获取原始 PyMuPDF 文档对象（供高级操作使用）"""
        return self._doc
