## 背景

来自 Issue #9 (Obsidian CLI & Omnisearch 调研)。

Omnisearch 通过 Text Extractor 插件支持 OCR 和 PDF 文本提取，可以将图片和 PDF 中的内容纳入搜索范围。

当前 ZK CLI 仅支持 Markdown 文件的索引，无法处理图片和 PDF 中的知识。

## 目标

支持图片和 PDF 文件的文本提取，将非文本内容纳入知识库索引。

## 应用场景

1. **截图存档** - 将重要截图的文本内容提取并索引
2. **PDF 文献** - 学术论文、报告的文本提取
3. **扫描文档** - 纸质笔记的数字化存档
4. **白板照片** - 会议白板的照片转文本

## 技术方案

### 支持的文件类型

| 类型 | 格式 | 提取方式 |
|------|------|----------|
| PDF | .pdf | pdfplumber / PyMuPDF |
| 图片 | .png, .jpg | pytesseract (OCR) |

### 存储结构

```
~/.zettelkasten/
├── notes/           # Markdown 笔记（已有）
├── attachments/     # 附件文件
│   ├── pdfs/        # PDF 文件
│   │   └── paper-2026-03.pdf
│   └── images/      # 图片文件
│       └── whiteboard-2026-03.png
└── .zk/
    └── extracted/   # 提取的文本缓存
        └── paper-2026-03.txt
```

## 实现方案

### 1. 文本提取模块 `zk/extractor.py`

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

class TextExtractor(ABC):
    """文本提取器基类"""
    
    @abstractmethod
    def extract(self, filepath: Path) -> str:
        """从文件提取文本"""
        pass
    
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名"""
        pass

class PDFExtractor(TextExtractor):
    """PDF 文本提取"""
    
    def __init__(self):
        import pdfplumber
        self.pdfplumber = pdfplumber
    
    def extract(self, filepath: Path) -> str:
        text = []
        with self.pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text() or "")
        return "\n\n".join(text)
    
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

class ImageOCR(TextExtractor):
    """图片 OCR 提取"""
    
    def __init__(self, lang: str = "chi_sim+eng"):
        import pytesseract
        from PIL import Image
        self.pytesseract = pytesseract
        self.Image = Image
        self.lang = lang
    
    def extract(self, filepath: Path) -> str:
        image = self.Image.open(filepath)
        return self.pytesseract.image_to_string(image, lang=self.lang)
    
    def supported_extensions(self) -> List[str]:
        return [".png", ".jpg", ".jpeg", ".gif", ".bmp"]

class ExtractionManager:
    """提取管理器"""
    
    def __init__(self):
        self.extractors: List[TextExtractor] = [
            PDFExtractor(),
            ImageOCR(),
        ]
        self.cache_dir = get_config().zk_dir / "extracted"
    
    def extract(self, filepath: Path) -> Optional[str]:
        """提取文件文本"""
        # 检查缓存
        cache_file = self._get_cache_file(filepath)
        if cache_file.exists():
            return cache_file.read_text(encoding='utf-8')
        
        # 找到合适的提取器
        for extractor in self.extractors:
            if filepath.suffix.lower() in extractor.supported_extensions():
                text = extractor.extract(filepath)
                # 缓存结果
                self._save_cache(filepath, text)
                return text
        
        return None
    
    def _get_cache_file(self, filepath: Path) -> Path:
        """获取缓存文件路径"""
        cache_name = f"{filepath.stem}.txt"
        return self.cache_dir / cache_name
    
    def _save_cache(self, filepath: Path, text: str):
        """保存缓存"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._get_cache_file(filepath)
        cache_file.write_text(text, encoding='utf-8')
```

### 2. 索引集成

```python
# indexer.py
class Indexer:
    def index_attachments(self):
        """索引附件文件"""
        attachments_dir = config.base_dir / "attachments"
        
        for ext in [".pdf", ".png", ".jpg"]:
            for filepath in attachments_dir.rglob(f"*{ext}"):
                # 提取文本
                text = self.extraction_manager.extract(filepath)
                
                if text:
                    # 创建虚拟笔记用于索引
                    virtual_note = Note(
                        id=f"attach-{filepath.stem}",
                        title=filepath.name,
                        content=text[:1000] + "...",  # 限制长度
                        type=NoteType.LITERATURE,
                        source=str(filepath),
                        tags=["attachment", ext[1:]]
                    )
                    
                    # 添加到向量索引
                    self.vector_store.add_note(virtual_note)
```

### 3. CLI 接口

```bash
# 添加附件并索引
zk attach add paper.pdf --extract
zk attach add screenshot.png --extract

# 查看附件列表
zk attach list

# 重新提取（更新缓存）
zk attach reextract paper.pdf

# 搜索包含附件内容
zk search "OCR 提取的文本"
```

### 4. 笔记中引用附件

```markdown
---
id: '20260322143000'
title: 论文阅读
type: literature
attachments:
  - paper.pdf
---

# 论文阅读

[[附件: paper.pdf]]

提取摘要：本文提出了一种新的...
```

## 新增依赖

```txt
# PDF 提取 (二选一)
pdfplumber>=0.10.0    # 纯 Python，易安装
PyMuPDF>=1.23.0       # 功能更强，需要编译

# OCR
pytesseract>=0.3.10
Pillow>=10.0.0
```

**系统依赖：**
- Tesseract OCR: `apt-get install tesseract-ocr` / `brew install tesseract`
- 中文语言包: `apt-get install tesseract-ocr-chi-sim`

## 性能考虑

- OCR 较慢（几秒钟/图片），需要异步处理
- PDF 提取相对快，但大文件仍需时间
- 使用缓存避免重复提取

## 替代方案（推荐先实现）

考虑到复杂度和依赖问题，可以先实现简化版：

```python
# 简化方案：仅支持 PDF，使用纯 Python 库
class SimplePDFExtractor:
    """简化版 PDF 提取，使用 pdfplumber"""
    pass

# OCR 作为可选插件，不强制依赖
```

## 验收标准

- [ ] 文本提取模块 `zk/extractor.py`
- [ ] PDF 文本提取支持
- [ ] 缓存机制
- [ ] `zk attach` 子命令
- [ ] 附件内容纳入搜索
- [ ] 安装文档（含系统依赖）

## 优先级

**低** - 功能复杂，依赖多，建议后续考虑

## 依赖

- Issue #9 (Obsidian CLI 调研)
