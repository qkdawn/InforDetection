"""Create a sharp, human digital-life observation from one topic."""

from __future__ import annotations

import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .ai.client import AIClient
from .ai.utils import parse_json_response
from .mcp.horizon_adapter import (
    load_config,
    load_runtime,
    resolve_config_path,
    resolve_horizon_path,
)


class InsightCandidate(BaseModel):
    label: str
    thesis: str
    hidden_payoff: str
    emotional_cost: str
    recognition_line: str
    new_information: str
    overreach_risk: str

    @field_validator("*")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("candidate text must not be empty")
        return value


class InsightPool(BaseModel):
    candidates: list[InsightCandidate] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_distinct_labels(self) -> "InsightPool":
        labels = [candidate.label for candidate in self.candidates]
        if len(set(labels)) != len(labels):
            raise ValueError("candidate labels must be distinct")
        return self


class EmotionalInsight(BaseModel):
    selected_label: str
    psychology_concept: str
    concept_definition: str
    mechanism_steps: list[str] = Field(min_length=2, max_length=4)
    boundary: str
    lived_moment: str
    visible_behavior: str
    hidden_conflict: str
    hidden_payoff: str
    emotional_cost: str
    uncomfortable_truth: str
    core_thesis: str
    what_it_adds: str
    counterweight: str
    emotional_arc: list[str] = Field(min_length=3, max_length=4)
    visual_motif: str
    rejected_labels: list[str] = Field(min_length=2, max_length=5)
    rejected_cliches: list[str] = Field(min_length=3, max_length=8)

    @field_validator("*")
    @classmethod
    def clean_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            if not value:
                raise ValueError("insight text must not be empty")
        return value


class CardPage(BaseModel):
    role: Literal["cover", "scene", "turn", "aftertaste"]
    eyebrow: str
    headline: str
    body: str = ""
    pull_quote: str = ""

    @field_validator("eyebrow", "headline", "body", "pull_quote")
    @classmethod
    def clean_page_text(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_density(self) -> "CardPage":
        if not self.eyebrow or not self.headline:
            raise ValueError("every page needs an eyebrow and headline")
        if len(self.eyebrow) > 12:
            raise ValueError("page eyebrow must be at most 12 characters")
        if len(self.headline) > 32:
            raise ValueError("page headline must be at most 32 characters")
        if len(self.body) > 90:
            raise ValueError("page body must be at most 90 characters")
        if len(self.pull_quote) > 32:
            raise ValueError("page pull_quote must be at most 32 characters")
        if self.role != "cover" and not (self.body or self.pull_quote):
            raise ValueError("non-cover pages need body or pull_quote")
        return self


class EditorialScript(BaseModel):
    title: str
    subtitle: str
    mood: Literal["克制", "尖锐", "酸涩", "温柔", "冷静"]
    pages: list[CardPage] = Field(min_length=4, max_length=4)
    caption: str
    tags: list[str] = Field(min_length=3, max_length=6)

    @field_validator("title", "subtitle", "caption")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("text must not be empty")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned = [" ".join(value.lstrip("#").split()) for value in values]
        if any(not value for value in cleaned):
            raise ValueError("tags must not be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_story(self) -> "EditorialScript":
        roles = [page.role for page in self.pages]
        if roles != ["cover", "scene", "turn", "aftertaste"]:
            raise ValueError("deck must use cover, scene, turn, aftertaste in order")
        if len(self.title) > 30 or len(self.subtitle) > 40:
            raise ValueError("title or subtitle is too long")
        if not 80 <= len(self.caption) <= 280:
            raise ValueError("caption must contain 80-280 characters")
        pull_quotes = sum(bool(page.pull_quote) for page in self.pages)
        if pull_quotes > len(self.pages):
            raise ValueError("deck must use at most one pull quote per page")
        combined = " ".join(
            [self.title, self.subtitle, self.caption]
            + [f"{page.headline} {page.body} {page.pull_quote}" for page in self.pages]
        )
        unsafe = ("诊断为", "说明你患有", "证明他不爱", "一定是依恋", "都是因为童年")
        if any(phrase in combined for phrase in unsafe):
            raise ValueError("content makes an unsupported diagnostic claim")
        tired = (
            "认真接住",
            "在意的分量",
            "找到落点",
            "让藏了很久的话见光",
            "关系会顺着",
            "留一句给自己",
            "治愈自己",
            "停止内耗",
        )
        hits = [phrase for phrase in tired if phrase in combined]
        if hits:
            raise ValueError("content uses tired emotional-copy phrases: " + ", ".join(hits))
        return self


class EditorialScores(BaseModel):
    novelty: int = Field(ge=1, le=10)
    recognition: int = Field(ge=1, le=10)
    honesty: int = Field(ge=1, le=10)
    progression: int = Field(ge=1, le=10)
    human_voice: int = Field(ge=1, le=10)
    specificity: int = Field(ge=1, le=10)


class EditorialReview(BaseModel):
    verdict: Literal["pass", "revised"]
    scores: EditorialScores
    topic_delta: str
    cliche_hits: list[str] = Field(max_length=8)
    fabricated_details: list[str] = Field(max_length=8)
    notes: list[str] = Field(min_length=1, max_length=6)
    final_script: EditorialScript

    @model_validator(mode="after")
    def validate_pass_scores(self) -> "EditorialReview":
        if self.verdict == "pass" and min(self.scores.model_dump().values()) < 8:
            raise ValueError("a passing review requires every score to be at least 8")
        if len("".join(self.topic_delta.split())) < 12:
            raise ValueError("topic_delta must state the concrete information gain")
        return self


def normalize_psychology_input(topic: str, context: str = "") -> tuple[str, str]:
    if not isinstance(topic, str):
        raise ValueError("topic must be a string")
    if not isinstance(context, str):
        raise ValueError("context must be a string")
    topic = " ".join(topic.split())
    context = " ".join(context.split())
    if not 4 <= len(topic) <= 200:
        raise ValueError("topic must contain 4-200 characters")
    if len(context) > 2000:
        raise ValueError("context must not exceed 2000 characters")
    return topic, context


def _angles_prompt(topic: str, context: str) -> tuple[str, str]:
    system = """你是《屏幕里的我们》的选题编辑。你不查资料，也不写成品。
你要为一个数字生活现象提出 6 个互相竞争的解释角度，给后面的主编挑选。

这一步不是找最温柔、最容易共鸣的说法，而是找读者没立刻想到，却会突然认出自己的解释。

硬规则：
- 6 个角度必须结构不同，不能只是同一句话换词。
- 最多 1 个角度可以停留在“因为在意、害怕做不好、害怕下一步”。
- 至少 4 个角度要指出这种行为带来的隐秘收益，例如避免负责、保留选项、维持自我形象、把决定交给时间、试探关系或夺回控制感。
- 每个角度都要说明代价。不能只替当事人开脱。
- recognition_line 写一句当事人脑内真正可能闪过的话。短一点，不要金句。
- new_information 必须回答：这个角度比原选题多告诉了读者什么？
- 不使用心理学术语，不诊断，不把一种解释说成所有人的真相。
- 不编造时间、次数、人物关系或生活道具。
- 禁止“接住、分量、落点、见光、治愈、内耗”等情绪博主套话。

只返回 JSON：
{
  "candidates":[
    {
      "label":"角度短名",
      "thesis":"这个角度的核心判断",
      "hidden_payoff":"这种行为悄悄替当事人完成了什么",
      "emotional_cost":"它让谁承担了什么代价",
      "recognition_line":"一句不漂亮但真实的脑内话",
      "new_information":"它比原选题新增的认识",
      "overreach_risk":"这个角度最容易武断在哪里"
    }
  ]
}"""
    user = f"原选题：{topic}\n补充语境：{context or '无'}"
    return system, user


def _selection_prompt(
    topic: str, context: str, pool: InsightPool
) -> tuple[str, str]:
    system = """你是《屏幕里的我们》的心理现象科普主编。下面有 6 个候选解释。
选择标准按顺序是：解释力、信息增量、生活中的认出感、能否对应一个可靠且不过度诊断的心理现象。

先做闭卷测试：如果只看原选题，读者已经能猜到候选结论，这个候选就淘汰。
“因为太在意”“想认真回复”“害怕关系进入下一步”通常只是复述题面，除非它还能指出一个更隐秘的行为收益。

优先选择既能解释行为，又能展开讨论的角度。好的判断要说清楚：
表面行为是什么、人在回避或调节什么、这个过程为什么会自我强化，以及它把什么成本转移给了别人。
如果 6 个候选都不够好，可以综合出一个新角度，并把 selected_label 写成“主编综合”。

要求：
- selected_label 保留被选中的候选角度短名，用来说明选角来源；它不承担心理学概念命名。
- psychology_concept 必须是通行的心理学概念或描述性现象名称，不能是修辞比喻。可选方向包括“回避性应对”“决策回避”“拖延式情绪调节”“不确定性规避”“认知失调”“控制感补偿”。
- concept_definition 用一句白话定义该概念，不得循环解释概念名称。
- mechanism_steps 用 2-4 个短句写出“触发 -> 当下收益 -> 行为持续”的因果过程。
- boundary 明确什么情况不能用该概念解释，以及不能据此判断什么。
- core_thesis 最多两句，必须解释“诱因 -> 心理处理 -> 可见行为”的过程，不能写成万能金句。
- hidden_payoff 是必填核心，不得用“缓解焦虑”这种空泛答案。
- what_it_adds 说明这个心理现象如何帮助理解原问题，而不只是给行为贴标签。
- counterweight 说明适用边界：它不是所有人的解释，也不能据此判断人格、关系或疾病。
- lived_moment 只能使用原选题或语境里已有的动作，不能添加具体时间、次数、对象或道具。
- rejected_cliches 列出本题最容易写出的至少 3 条俗套结论。
- 不引用未经提供的研究、比例或实验；不诊断人格、创伤、依恋类型或疾病。

只返回 JSON：
{
  "selected_label":"候选标签或主编综合",
  "psychology_concept":"通行的心理现象名称，不得使用比喻",
  "concept_definition":"一句白话定义",
  "mechanism_steps":["触发","当下收益","行为结果"],
  "boundary":"适用边界与不能据此判断的内容",
  "lived_moment":"原输入支持的可见瞬间",
  "visible_behavior":"表面行为",
  "hidden_conflict":"两股真实力量",
  "hidden_payoff":"拖延或回避替当事人完成了什么",
  "emotional_cost":"谁在为这种收益付代价",
  "uncomfortable_truth":"最不讨好当事人的那句判断",
  "core_thesis":"全篇唯一核心判断",
  "what_it_adds":"相比原选题新增了什么认识",
  "counterweight":"边界与代价",
  "emotional_arc":["认出动作","听见借口","看见收益","留下代价"],
  "visual_motif":"不靠苦脸人物的数字行为画面",
  "rejected_labels":["至少2个被淘汰标签"],
  "rejected_cliches":["至少3条本题俗套结论"]
}"""
    user = (
        f"原选题：{topic}\n补充语境：{context or '无'}\n"
        f"候选角度：{pool.model_dump_json(indent=2)}"
    )
    return system, user


def _script_prompt(
    topic: str, context: str, insight: EmotionalInsight
) -> tuple[str, str]:
    system = """你是《屏幕里的我们》的心理现象科普作者。把一个数字生活问题写成 4 页小红书讨论卡片。
这是“问题讨论 + 心理现象解释”，不是情绪文案、心理诊断或学术论文。

读者看完必须能回答三件事：这种行为是什么、背后可能有什么心理过程、这个解释的边界在哪里。
心理现象名称只是解释工具，不能当成给人贴的标签。

页面任务：
- cover：把原问题改写成一个明确、具体、让人想继续翻页的问题；不要先给结论。
- scene：讨论常见解释。说明它为什么有一部分道理，又遗漏了什么。
- turn：headline 或 eyebrow 必须原样出现 psychology_concept，并用生活语言解释 mechanism_steps。这是科普核心页。
- aftertaste：说明适用边界、可能影响和更准确的理解方式。可以留下一个具体讨论问题，但不要灌鸡汤。

写作规则：
- 只能使用原选题和语境里已有的事实。禁止编造几点几分、打开几次、过了几分钟、杯子凉了、群聊数量、人物关系等细节。
- 现象名称出现 1-2 次即可，第一次出现后必须使用 concept_definition 解释，不能堆术语。
- 使用“可能、往往、在一些情况下”等准确措辞，不把一种解释说成所有人的真相。
- 全组只允许 1-2 个 pull_quote，用来写定义或机制摘要，不用来制造情绪金句。
- 不要连续使用“不是……而是……”；全组最多一次。
- 禁止排比三连、象征隐喻、疗愈口吻和对当事人的讨好。
- 禁止“接住、分量、落点、见光、顺着它走、留一句给自己、真正难的是、说到底、停止内耗”等套话。
- 禁止“研究表明、心理学发现、某效应证明”等无来源表述，也不要虚构百分比、实验或专家意见。
- 固定 4 页，顺序必须是 cover、scene、turn、aftertaste。
- cover 的 eyebrow 必须是内容线索，不能写栏目名“屏幕里的我们”。
- eyebrow 不超过 12 字，headline 不超过 32 字，body 不超过 90 字，pull_quote 不超过 32 字。
- caption 80-280 字，完成一段独立的问题讨论：现象、机制、边界缺一不可。

只返回 JSON：
{
  "title":"整组标题，不超过30字",
  "subtitle":"一句暗线，不超过40字",
  "mood":"克制|尖锐|酸涩|温柔|冷静",
  "pages":[
    {"role":"cover|scene|turn|aftertaste","eyebrow":"...","headline":"...","body":"...","pull_quote":"..."}
  ],
  "caption":"80-280字",
  "tags":["3-6个标签，不带#"]
}"""
    user = (
        f"原选题：{topic}\n补充语境：{context or '无'}\n"
        f"选中洞察：{insight.model_dump_json(indent=2)}"
    )
    return system, user


def _review_prompt(
    topic: str,
    context: str,
    insight: EmotionalInsight,
    script: EditorialScript,
) -> tuple[str, str]:
    system = """你是《屏幕里的我们》的苛刻科普主编。审一组 4 页心理现象讨论卡片，并直接交付终稿。

先回答一个问题：它比原选题到底多说了什么？把答案写入 topic_delta。
如果答案只是“更在意、更纠结、害怕下一步”，原创性不得超过 6 分，必须重写。

逐项检查：
1. novelty：psychology_concept 是否是通行概念而非自创比喻，并且真的解释了一个心理过程。
2. recognition：读者能否把概念对应到具体数字生活行为。
3. honesty：是否说明适用边界，既不诊断、不定罪，也不替当事人开脱。
4. progression：是否严格完成“问题 -> 常见解释 -> 心理机制 -> 边界与影响”。
5. human_voice：是否像清楚的人在做科普，而不是情绪博主、教科书或 AI 金句机。
6. specificity：机制是否具体，但没有虚构研究、比例、实验、时间、对象和道具。

必须扫描并删除：
- “接住、分量、落点、见光、治愈、内耗、真正难的是、留一句给自己”等套话。
- 为了显得真实而编造的时间、次数、群聊、杯子、夜晚和关系细节。
- 无来源的“研究表明、心理学发现、某效应证明”，以及听起来专业但无法解释行为的术语。
- 把“回复即签字、消息贬值、沉默在说话”之类修辞包装成心理现象名称。
- 连续的“不是……而是……”，三段排比，每页一句制造出来的金句。

只要有一项低于 8 分，就重写并将 verdict 设为 revised。无论 verdict 是什么，
final_script 都必须是完整终稿。重写时忠于选中的心理现象、hidden_payoff 和 counterweight，
不要退回“因为太在意”的安全结论，也不要写成诊断建议。

只返回 JSON：
{
  "verdict":"pass|revised",
  "scores":{"novelty":1,"recognition":1,"honesty":1,"progression":1,"human_voice":1,"specificity":1},
  "topic_delta":"终稿相比原选题新增的具体认识",
  "cliche_hits":["发现并已删除的套话，可为空"],
  "fabricated_details":["发现并已删除的假细节，可为空"],
  "notes":["1-6条简短主编意见"],
  "final_script":{
    "title":"...","subtitle":"...","mood":"克制|尖锐|酸涩|温柔|冷静",
    "pages":[{"role":"cover|scene|turn|aftertaste","eyebrow":"...","headline":"...","body":"...","pull_quote":"..."}],
    "caption":"80-280字","tags":["..."]
  }
}"""
    user = (
        f"原选题：{topic}\n补充语境：{context or '无'}\n"
        f"选中洞察：{insight.model_dump_json(indent=2)}\n"
        f"待审分镜：{script.model_dump_json(indent=2)}"
    )
    return system, user


def _validate_no_fabricated_numbers(
    script: EditorialScript, topic: str, context: str
) -> None:
    source = f"{topic} {context}"
    combined = " ".join(
        [script.title, script.subtitle, script.caption]
        + [f"{page.eyebrow} {page.headline} {page.body} {page.pull_quote}" for page in script.pages]
    )
    if not re.search(r"\d", source) and re.search(r"\d", combined):
        raise ValueError("script invents exact numeric details not present in the input")


class PsychologyBriefGenerator:
    def __init__(self, client: AIClient):
        self.client = client

    async def _model(
        self,
        model: type[BaseModel],
        *,
        system: str,
        user: str,
        temperature: float,
        validator: Callable[[Any], None] | None = None,
    ) -> Any:
        validation_error: Exception | None = None
        for _ in range(2):
            response = await self.client.complete(
                system=system, user=user, temperature=temperature
            )
            try:
                result = model.model_validate(parse_json_response(response))
                if validator:
                    validator(result)
                return result
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                user += "\n\n只返回修正后的 JSON。校验错误：" + str(exc)
        raise ValueError(f"Invalid {model.__name__} response") from validation_error

    async def angles(self, topic: str, context: str = "") -> dict[str, Any]:
        topic, context = normalize_psychology_input(topic, context)
        system, user = _angles_prompt(topic, context)
        result = await self._model(
            InsightPool, system=system, user=user, temperature=0.95
        )
        return result.model_dump()

    async def insight(
        self,
        *,
        topic: str,
        context: str = "",
        angles_payload: dict[str, Any],
    ) -> dict[str, Any]:
        topic, context = normalize_psychology_input(topic, context)
        pool = InsightPool.model_validate(angles_payload)
        system, user = _selection_prompt(topic, context, pool)
        result = await self._model(
            EmotionalInsight, system=system, user=user, temperature=0.55
        )
        return result.model_dump()

    async def script(
        self,
        *,
        topic: str,
        context: str,
        insight_payload: dict[str, Any],
    ) -> dict[str, Any]:
        topic, context = normalize_psychology_input(topic, context)
        insight = EmotionalInsight.model_validate(insight_payload)
        system, user = _script_prompt(topic, context, insight)
        result = await self._model(
            EditorialScript,
            system=system,
            user=user,
            temperature=0.8,
            validator=lambda value: _validate_no_fabricated_numbers(
                value, topic, context
            ),
        )
        return result.model_dump()

    async def review(
        self,
        *,
        topic: str,
        context: str,
        insight_payload: dict[str, Any],
        script_payload: dict[str, Any],
    ) -> dict[str, Any]:
        topic, context = normalize_psychology_input(topic, context)
        insight = EmotionalInsight.model_validate(insight_payload)
        script = EditorialScript.model_validate(script_payload)
        system, user = _review_prompt(topic, context, insight, script)
        result = await self._model(
            EditorialReview,
            system=system,
            user=user,
            temperature=0.45,
            validator=lambda value: _validate_no_fabricated_numbers(
                value.final_script, topic, context
            ),
        )
        return result.model_dump()

    async def generate(self, topic: str, context: str = "") -> dict[str, Any]:
        topic, context = normalize_psychology_input(topic, context)
        angles = await self.angles(topic, context)
        insight = await self.insight(
            topic=topic, context=context, angles_payload=angles
        )
        draft = await self.script(
            topic=topic, context=context, insight_payload=insight
        )
        review = await self.review(
            topic=topic,
            context=context,
            insight_payload=insight,
            script_payload=draft,
        )
        return {
            "topic": topic,
            "context": context,
            "angles": angles,
            "insight": insight,
            "draft": draft,
            "review": {key: value for key, value in review.items() if key != "final_script"},
            "script": review["final_script"],
        }


def create_psychology_generator(
    *, horizon_path: str | None = None, config_path: str | None = None
) -> PsychologyBriefGenerator:
    resolved_horizon = resolve_horizon_path(horizon_path)
    runtime = load_runtime(resolved_horizon)
    resolved_config = resolve_config_path(resolved_horizon, config_path)
    config = load_config(runtime, resolved_config)
    return PsychologyBriefGenerator(runtime.create_ai_client(config.ai))
