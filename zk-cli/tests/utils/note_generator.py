"""
测试笔记生成器

生成各种测试数据用于集成测试
"""

import random
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

from zk.models import Note, NoteType


# 预定义笔记模板
NOTE_TEMPLATES = {
    "technology": [
        {
            "title": "Python 编程技巧",
            "content": "Python 是一种强大的编程语言。{detail} 在数据处理方面特别有用。",
            "tags": ["python", "programming"],
        },
        {
            "title": "机器学习基础",
            "content": "机器学习是人工智能的核心。{detail} 监督学习是其中最重要的范式之一。",
            "tags": ["ml", "ai"],
        },
        {
            "title": "深度学习介绍",
            "content": "深度学习使用神经网络。{detail} 它在图像识别方面取得了突破。",
            "tags": ["dl", "ai", "neural-networks"],
        },
        {
            "title": "Docker 容器化",
            "content": "Docker 改变了部署方式。{detail} 容器化使应用移植更加容易。",
            "tags": ["docker", "devops"],
        },
        {
            "title": "Git 版本控制",
            "content": "Git 是分布式版本控制系统。{detail} 分支管理是其核心特性。",
            "tags": ["git", "version-control"],
        },
    ],
    "science": [
        {
            "title": "量子力学基础",
            "content": "量子力学描述微观世界。{detail} 波粒二象性是其核心概念。",
            "tags": ["physics", "quantum"],
        },
        {
            "title": "相对论简介",
            "content": "爱因斯坦的相对论改变了我们对时空的理解。{detail} 时间 dilation 是其中一个效应。",
            "tags": ["physics", "relativity"],
        },
        {
            "title": "进化论",
            "content": "达尔文的进化论解释了物种起源。{detail} 自然选择是主要驱动力。",
            "tags": ["biology", "evolution"],
        },
        {
            "title": "DNA 结构",
            "content": "DNA 是遗传信息的载体。{detail} 双螺旋结构是其标志性特征。",
            "tags": ["biology", "genetics"],
        },
    ],
    "philosophy": [
        {
            "title": "存在主义",
            "content": "存在主义关注个体存在。{detail} 萨特是重要的代表人物。",
            "tags": ["philosophy", "existentialism"],
        },
        {
            "title": "认识论",
            "content": "认识论研究知识的本质。{detail} 我们如何知道什么是真实的？",
            "tags": ["philosophy", "epistemology"],
        },
        {
            "title": "道德哲学",
            "content": "道德哲学探讨善恶标准。{detail} 功利主义和义务论是两大流派。",
            "tags": ["philosophy", "ethics"],
        },
    ],
    "productivity": [
        {
            "title": "番茄工作法",
            "content": "番茄工作法提高专注度。{detail} 25 分钟工作 + 5 分钟休息。",
            "tags": ["productivity", "time-management"],
        },
        {
            "title": "Zettelkasten 方法",
            "content": "卡片盒笔记法由卢曼发明。{detail} 双向链接是其核心特性。",
            "tags": ["zettelkasten", "note-taking"],
        },
        {
            "title": "GTD 方法",
            "content": "Getting Things Done 是任务管理系统。{detail} 收集、处理、组织、回顾、执行。",
            "tags": ["gtd", "productivity"],
        },
    ],
}

# 详情填充内容
DETAILS = [
    "值得注意的是",
    "更重要的是",
    "研究表明",
    "实践证明",
    "从历史来看",
    "根据统计",
    "专家们认为",
    "经验告诉我们",
    "事实上",
    "简单来说",
]


@dataclass
class GeneratedNote:
    """生成的笔记数据"""
    title: str
    content: str
    note_type: NoteType
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    
    def to_note(self, note_id: Optional[str] = None) -> Note:
        """转换为 Note 对象"""
        from datetime import datetime
        
        now = datetime.now()
        return Note(
            id=note_id or datetime.now().strftime("%Y%m%d%H%M%S"),
            title=self.title,
            content=self.content,
            type=self.note_type,
            created=now,
            updated=now,
            tags=self.tags,
            links=self.links,
            backlinks=[],
        )


class NoteGenerator:
    """
    笔记生成器
    
    生成各种测试笔记数据
    
    用法:
        generator = NoteGenerator(seed=42)
        notes = generator.generate(100, NoteType.PERMANENT)
        linked_notes = generator.generate_with_links(50)
    """
    
    def __init__(self, seed: Optional[int] = None):
        """
        初始化生成器
        
        Args:
            seed: 随机种子（用于可复现）
        """
        if seed is not None:
            random.seed(seed)
        self._generated_titles: List[str] = []
    
    def generate(
        self, 
        count: int, 
        note_type: NoteType = NoteType.PERMANENT,
        category: Optional[str] = None
    ) -> List[GeneratedNote]:
        """
        生成笔记
        
        Args:
            count: 生成数量
            note_type: 笔记类型
            category: 指定类别（tech/science/philosophy/productivity）
            
        Returns:
            生成的笔记列表
        """
        notes = []
        
        # 选择模板
        if category and category in NOTE_TEMPLATES:
            templates = NOTE_TEMPLATES[category]
        else:
            # 混合所有类别
            templates = []
            for cat_templates in NOTE_TEMPLATES.values():
                templates.extend(cat_templates)
        
        for i in range(count):
            # 随机选择模板
            template = random.choice(templates)
            
            # 填充详情
            detail = random.choice(DETAILS)
            content = template["content"].format(detail=detail)
            
            # 添加唯一标识避免重复标题
            title = template["title"]
            if count > len(templates):
                title = f"{title} ({i+1})"
            
            note = GeneratedNote(
                title=title,
                content=content,
                note_type=note_type,
                tags=template["tags"].copy(),
            )
            
            notes.append(note)
            self._generated_titles.append(title)
        
        return notes
    
    def generate_with_links(
        self, 
        count: int,
        link_probability: float = 0.3
    ) -> List[GeneratedNote]:
        """
        生成带链接的笔记
        
        Args:
            count: 生成数量
            link_probability: 每条笔记包含链接的概率
            
        Returns:
            生成的笔记列表（部分包含 links）
        """
        notes = self.generate(count, NoteType.PERMANENT)
        
        # 为后面的笔记添加指向前面笔记的链接
        for i, note in enumerate(notes):
            if i > 0 and random.random() < link_probability:
                # 随机选择之前生成的 1-3 个笔记作为链接目标
                num_links = random.randint(1, min(3, i))
                target_indices = random.sample(range(i), num_links)
                
                for idx in target_indices:
                    # 使用 [[标题]] 格式
                    target_title = notes[idx].title
                    note.content += f" 参考 [[{target_title}]]。"
        
        return notes
    
    def generate_fleeting(self, count: int) -> List[GeneratedNote]:
        """生成闪念笔记"""
        return self.generate(count, NoteType.FLEETING)
    
    def generate_literature(self, count: int) -> List[GeneratedNote]:
        """生成文献笔记"""
        # 文献笔记通常有来源
        notes = self.generate(count, NoteType.LITERATURE)
        for note in notes:
            note.content += f"\n\nSource: Book {random.randint(1, 100)}, Page {random.randint(1, 300)}"
        return notes
    
    def generate_permanent(self, count: int) -> List[GeneratedNote]:
        """生成永久笔记"""
        return self.generate(count, NoteType.PERMANENT)
    
    def generate_mixed(self, count: int) -> Dict[NoteType, List[GeneratedNote]]:
        """
        生成混合类型的笔记
        
        Args:
            count: 总数量
            
        Returns:
            按类型分类的笔记字典
        """
        # 60% permanent, 30% fleeting, 10% literature
        p_count = int(count * 0.6)
        f_count = int(count * 0.3)
        l_count = count - p_count - f_count
        
        return {
            NoteType.PERMANENT: self.generate_permanent(p_count),
            NoteType.FLEETING: self.generate_fleeting(f_count),
            NoteType.LITERATURE: self.generate_literature(l_count),
        }
    
    def get_random_queries(self, count: int = 10) -> List[str]:
        """
        生成随机搜索查询
        
        Args:
            count: 查询数量
            
        Returns:
            查询字符串列表
        """
        queries = [
            "Python programming",
            "machine learning",
            "deep learning",
            "Docker containers",
            "quantum physics",
            "evolution theory",
            "existentialism",
            "productivity methods",
            "note taking",
            "time management",
            "artificial intelligence",
            "neural networks",
            "moral philosophy",
            "DNA structure",
            "relativity theory",
        ]
        
        return random.sample(queries, min(count, len(queries)))


def generate_test_dataset(size: str = "small") -> Dict[str, Any]:
    """
    生成标准测试数据集
    
    Args:
        size: small (50), medium (200), large (1000)
        
    Returns:
        测试数据集配置
    """
    sizes = {
        "small": 50,
        "medium": 200,
        "large": 1000,
    }
    
    count = sizes.get(size, 50)
    generator = NoteGenerator(seed=42)
    
    return {
        "size": size,
        "count": count,
        "notes": generator.generate_mixed(count),
        "queries": generator.get_random_queries(10),
    }
