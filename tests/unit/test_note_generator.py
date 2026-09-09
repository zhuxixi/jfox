"""NoteGenerator 抽样行为：无放回轮转保证标题唯一（#523 组 B）。

#483 防重双通道闸门后，add 命令拒绝重复标题；旧实现 random.choice
有放回抽样在 count 接近模板数时高概率撞标题（seed=0 时 15 选 15 撞 5 个），
导致 test_multiple_notes_with_links_batch flaky。
"""

from tests.utils.note_generator import NOTE_TEMPLATES, NoteGenerator

TEMPLATE_COUNT = sum(len(v) for v in NOTE_TEMPLATES.values())  # 15


class TestGenerateNoDuplicateTitles:
    def test_one_round_titles_unique(self):
        """一轮内（count == 模板数）标题不重复——seed=0 在旧实现下撞 5 个"""
        gen = NoteGenerator(seed=0)
        notes = gen.generate(TEMPLATE_COUNT)
        titles = [n.title for n in notes]
        assert len(titles) == TEMPLATE_COUNT
        assert len(set(titles)) == TEMPLATE_COUNT

    def test_count_below_pool_unique(self):
        """count 小于模板数：无后缀且不重复"""
        gen = NoteGenerator(seed=7)
        notes = gen.generate(TEMPLATE_COUNT - 1)
        titles = [n.title for n in notes]
        assert len(set(titles)) == len(titles)
        assert not any("(" in t for t in titles)

    def test_count_above_pool_suffixed_unique(self):
        """count 超过模板数：后缀规则生效，跨轮全局唯一"""
        gen = NoteGenerator(seed=3)
        notes = gen.generate(TEMPLATE_COUNT + 5)
        titles = [n.title for n in notes]
        assert len(set(titles)) == len(titles)
        assert all("(" in t for t in titles)

    def test_no_seed_still_unique(self):
        """无 seed（全局随机态）：唯一性不依赖可复现性"""
        gen = NoteGenerator()
        notes = gen.generate(TEMPLATE_COUNT)
        titles = [n.title for n in notes]
        assert len(set(titles)) == TEMPLATE_COUNT

    def test_cross_call_titles_unique(self):
        """同一 generator 多次调 generate（generate_mixed 等场景）：跨调用全局唯一"""
        gen = NoteGenerator(seed=5)
        titles = [n.title for n in gen.generate(TEMPLATE_COUNT)]
        titles += [n.title for n in gen.generate_fleeting(5)]
        titles += [n.title for n in gen.generate_literature(5)]
        assert len(set(titles)) == len(titles)
