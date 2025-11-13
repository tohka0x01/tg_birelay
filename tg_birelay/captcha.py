from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


@dataclass
class Challenge:
    """验证码题目实体。"""

    label: str
    question: str
    answer: str
    display: Optional[str] = None

    def render(self) -> str:
        hint_line = f"\n💡 提示：{self.display}" if self.display else ""
        return f"🧩 {self.label}\n\n{self.question}{hint_line}\n\n请直接回复答案。"


ChallengeFactory = Callable[[], Challenge]


def _math_quiz() -> Challenge:
    style = random.choice(["加减", "乘法", "优先级"])
    if style == "加减":
        a, b = random.randint(10, 99), random.randint(10, 99)
        op = random.choice(["+", "-"])
        answer = a + b if op == "+" else a - b
        expr = f"{a} {op} {b} = ?"
    elif style == "乘法":
        a, b = random.randint(2, 12), random.randint(2, 12)
        answer = a * b
        expr = f"{a} × {b} = ?"
    else:
        a, b, c = random.randint(5, 20), random.randint(1, 10), random.randint(1, 10)
        expr = f"{a} + {b} × {c} = ?"
        answer = a + b * c
    return Challenge("心算闯关", f"请计算：{expr}", str(answer))


def _sequence_quiz() -> Challenge:
    base = random.randint(1, 9)
    delta = random.randint(2, 5)
    seq = [base + i * delta for i in range(4)]
    question = ", ".join(map(str, seq)) + ", ?"
    return Challenge("数列推理", f"请补全下一项：{question}", str(base + 4 * delta))


def _chinese_number() -> Challenge:
    digits = "零一二三四五六七八九"
    num = random.randint(10, 99)
    tens, ones = divmod(num, 10)
    if tens == 1:
        chinese = "十" + (digits[ones] if ones else "")
    else:
        chinese = digits[tens] + "十" + (digits[ones] if ones else "")
    return Challenge("中文数字", "请把下列汉字数字换算成阿拉伯数字：", str(num), chinese)


def _logic_quiz() -> Challenge:
    scenarios = [
        lambda: ("年龄推理", random.randint(5, 12)),
        lambda: ("水果剩余", random.randint(6, 12)),
    ]
    tag, base = random.choice(scenarios)()
    if tag == "年龄推理":
        answer = base + 5
        text = f"小李现在 {base} 岁，5 年后几岁？"
    else:
        answer = base - 3
        text = f"篮子里有 {base} 个苹果，吃掉 3 个还剩多少？"
    return Challenge("逻辑推演", text, str(answer))


def _clock_quiz() -> Challenge:
    hour = random.randint(0, 23)
    minute = random.choice([0, 15, 30, 45])
    periods = ["清晨", "上午", "下午", "夜间"]
    label = random.choice(periods)
    human = f"{label} {hour:02d}:{minute:02d}"
    return Challenge("时间换算", "请写出 24 小时制时间（HH:MM）：", f"{hour:02d}:{minute:02d}", human)


CHALLENGE_REGISTRY: dict[str, tuple[str, ChallengeFactory]] = {
    "math": ("心算闯关", _math_quiz),
    "sequence": ("数列推理", _sequence_quiz),
    "chinese": ("中文数字", _chinese_number),
    "logic": ("逻辑推演", _logic_quiz),
    "clock": ("时间换算", _clock_quiz),
}

CHALLENGE_OPTIONS = {key: meta[0] for key, meta in CHALLENGE_REGISTRY.items()}


def build_challenge(allowed: Optional[Sequence[str]] = None) -> Challenge:
    """根据可选题库生成题目，若为空则退回默认题库。"""
    pools = [key for key in (allowed or CHALLENGE_REGISTRY.keys()) if key in CHALLENGE_REGISTRY]
    if not pools:
        pools = list(CHALLENGE_REGISTRY.keys())
    key = random.choice(pools)
    _, factory = CHALLENGE_REGISTRY[key]
    return factory()
