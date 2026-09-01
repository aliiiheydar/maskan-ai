"""Evaluation harness for Persian intent extraction (app/llm/intent_extractor).

Two kinds of check, because the task has two kinds of output:

  * Structured fields (budget, area, neighborhoods, booleans) have one right
    answer, so they are asserted directly. An LLM judge on a number is just a
    slower, less reliable `==`.
  * The weight vector, the reachability dial and the financial persona are
    judgements about emphasis, where several answers are defensible. Those are
    scored by an LLM judge that is shown the user's words and the extracted
    weights and asked whether the emphasis was read correctly.

Run:  python3 -m evals.intent_eval           (all cases)
      python3 -m evals.intent_eval --quick   (single-turn cases only)
"""

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.models import ExtractedSearchIntent
from app.llm.client import OpenRouterClient
from app.llm.dialogue_generator import stream_chat_reply
from app.llm.intent_extractor import extract_search_intent

MILLION = 1_000_000


@dataclass
class Case:
    name: str
    # The turns leading up to the one being extracted; empty for single-turn.
    history: list[dict[str, str]] = field(default_factory=list)
    message: str = ""
    # field -> expected value. A tuple means "anywhere in this inclusive
    # range", which is how tolerances like "نوساز -> around 1400" are stated.
    expect: dict[str, Any] = field(default_factory=dict)
    # Fields that must come back at their default -- the hallucination check.
    # A vague message that produces a budget the user never gave is a worse
    # failure than a missing one: it silently filters out most of the city.
    forbid: tuple[str, ...] = ()
    # What the emphasis should look like, in words, for the judge.
    judge: Optional[str] = None
    # When set, the conversational reply for this turn is generated and graded
    # too: what the assistant *says* is half the product, and a turn that
    # extracts nothing is only correct if the reply goes and asks for it.
    reply_judge: Optional[str] = None
    group: str = "single"


SINGLE_TURN: list[Case] = [
    Case(
        group="single",
        name="deposit+rent colloquial millions",
        message="۲۰۰ پیش دارم ماهی ۱۵ تومن اجاره ولی تبدیل هم باشه",
        expect={"max_deposit": 200 * MILLION, "max_rent": 15 * MILLION, "can_convert": True},
    ),
    Case(
        group="single",
        name="neighborhoods + area range",
        message="تو ونک یا سعادت‌آباد، بین ۷۰ تا ۹۰ متر",
        expect={"min_area_sqm": 70, "max_area_sqm": 90, "target_neighborhoods": ["ونک", "سعادت‌آباد"]},
    ),
    Case(
        group="single",
        name="area ceiling only",
        message="زیر ۶۰ متر می‌خوام، بودجه‌ام کمه",
        expect={"max_area_sqm": 60, "min_area_sqm": None},
    ),
    Case(
        group="single",
        name="rooms + amenities",
        message="دو خوابه با آسانسور و پارکینگ و انباری",
        expect={"min_rooms": 2, "must_have_elevator": True, "must_have_parking": True, "must_have_storage": True},
    ),
    Case(
        group="single",
        name="full rahn",
        message="فقط رهن کامل می‌خوام، اجاره ماهانه نمی‌تونم بدم",
        expect={"full_rahn_only": True},
        judge=(
            "Wants رهن کامل and cannot pay monthly rent. financial_persona must be prefer_higher_deposit. "
            "A weight vector is optional here; judge mainly on the persona."
        ),
    ),
    Case(
        group="single",
        name="new build",
        message="نوساز باشه، ساختمون قدیمی نمی‌خوام",
        expect={"min_build_year": (1398, 1405)},
    ),
    Case(
        group="single",
        name="floor constraint",
        message="همکف نباشه، طبقه اول یا دوم خوبه",
        expect={"min_floor": (1, 1), "max_floor": (2, 3)},
    ),
    Case(
        group="single",
        name="metro priority",
        message="مهم‌ترین چیز برام نزدیکی به مترو است، قیمت زیاد مهم نیست",
        expect={},
        judge="Reachability is the top priority and price barely matters: commute_importance should be high (>=0.7) and the commute weight should dominate the weight vector while budget is small.",
    ),
    Case(
        group="single",
        name="car owner, commute unimportant",
        message="ماشین دارم، دسترسی به مترو برام مهم نیست. یه جای بزرگ و نوساز می‌خوام",
        expect={},
        judge="Reachability explicitly dismissed: commute_importance should be low (<=0.3). Area and freshness should carry more weight.",
    ),
    Case(
        group="single",
        name="cash constrained persona",
        message="پول پیش زیادی ندارم ولی اجاره ماهانه‌ش رو می‌تونم بدم",
        expect={"financial_persona": "prefer_higher_rent"},
    ),
    Case(
        group="single",
        name="min deposit floor",
        message="حداقل ۱۰۰ پیش، بالای ۱۰ تومن اجاره",
        expect={"min_deposit": 100 * MILLION, "min_rent": 10 * MILLION},
    ),
    Case(
        group="single",
        name="photos only",
        message="فقط آگهی‌هایی که عکس دارن رو نشونم بده",
        expect={"must_have_images": True},
    ),
    Case(
        group="single",
        name="explicit no conversion",
        message="تبدیل نمی‌خوام، همون مبلغ آگهی باشه",
        expect={"can_convert": False},
    ),
    Case(
        group="single",
        name="soft preferences",
        message="یه واحد نورگیر تو کوچه خلوت، حیاط داشته باشه عالیه",
        expect={},
        judge="Soft, descriptive qualities with no hard numbers: soft_preferences should be populated and soft_preference_summary non-empty; the soft weight should be meaningful.",
    ),
]

MULTI_TURN: list[Case] = [
    Case(
        group="multi",
        name="budget stated first, area later",
        history=[
            {"role": "user", "content": "سلام، دنبال آپارتمان اجاره‌ای هستم"},
            {"role": "assistant", "content": "سلام! بودجه و محله مورد نظرتان را بفرمایید."},
            {"role": "user", "content": "۳۰۰ پیش و ۲۰ اجاره"},
            {"role": "assistant", "content": "بسیار خوب. متراژ یا محله خاصی مد نظرتان هست؟"},
        ],
        message="حداقل ۸۰ متر باشه",
        expect={"min_area_sqm": 80, "max_deposit": 300 * MILLION, "max_rent": 20 * MILLION},
    ),
    Case(
        group="multi",
        name="correction of an earlier budget",
        history=[
            {"role": "user", "content": "۵۰۰ پیش دارم"},
            {"role": "assistant", "content": "متوجه شدم، ودیعه تا ۵۰۰ میلیون تومان."},
        ],
        message="ببخشید اشتباه گفتم، ۳۰۰ پیش دارم نه ۵۰۰",
        expect={"max_deposit": 300 * MILLION},
    ),
    Case(
        group="multi",
        name="neighborhood added in a later turn",
        history=[
            {"role": "user", "content": "دو خوابه با پارکینگ می‌خوام"},
            {"role": "assistant", "content": "چه محله‌ای مد نظرتان است؟"},
        ],
        message="نارمک یا تهرانپارس",
        expect={"target_neighborhoods": ["نارمک", "تهرانپارس"], "min_rooms": 2, "must_have_parking": True},
    ),
    Case(
        group="multi",
        name="priority expressed after the filters",
        history=[
            {"role": "user", "content": "تو یوسف‌آباد، ۲۰۰ پیش و ۱۲ اجاره، حدود ۷۰ متر"},
            {"role": "assistant", "content": "چند گزینه پیدا شد. اولویت اصلی‌تان چیست؟"},
        ],
        message="راستش قیمت از همه چیز مهم‌تره، حاضرم دورتر از مترو باشه",
        expect={},
        judge="Price is now the dominant priority and distance to metro is explicitly acceptable: the budget weight should dominate and commute_importance should be low. The earlier filters (یوسف‌آباد, budget, ~70m) should still be carried forward.",
    ),
    Case(
        group="multi",
        name="workplace and commute mode",
        history=[
            {"role": "user", "content": "دنبال خونه‌ام نزدیک محل کارم"},
            {"role": "assistant", "content": "محل کار شما کجاست و با چه وسیله‌ای رفت‌وآمد می‌کنید؟"},
        ],
        message="میدان ونک کار می‌کنم و با ماشین میرم",
        expect={"commute_mode": "drive"},
        # No emphasis words here, only facts, so the grader must not demand a
        # weight vector -- naming a workplace is a filter, not a priority.
        judge=(
            "Workplace named as میدان ونک and travel by car. commute_importance should be moderate-to-high "
            "(0.5-0.7) since a workplace was given. `weights` may legitimately be absent: the user stated "
            "facts, not priorities, so do not penalise their absence."
        ),
    ),
]


# Whole people, not single sentences: each of these is one home-seeker with a
# budget, a life and a priority, written the way they would actually type it.
# They are the cases that catch a model that handles clauses in isolation but
# loses half of a real paragraph.
PERSONAS: list[Case] = [
    Case(
        group="persona",
        name="persona: newlywed couple, area quality matters",
        message=(
            "سلام، من و همسرم تازه ازدواج کردیم و دنبال یه آپارتمان دو خوابه هستیم. "
            "۴۰۰ میلیون پیش داریم و تا ۱۸ تومن اجاره می‌تونیم بدیم. حتما آسانسور و پارکینگ داشته باشه. "
            "محله‌ش برامون مهمه، یه جای شیک و مدرن و امن باشه."
        ),
        expect={
            "max_deposit": 400 * MILLION,
            "max_rent": 18 * MILLION,
            "min_rooms": 2,
            "must_have_elevator": True,
            "must_have_parking": True,
        },
        judge=(
            "The couple explicitly say the محله matters and want a smart, modern, safe area: the "
            "`quality` weight must be clearly above its 0.10 baseline. Elevator/parking are filters, "
            "not emphasis."
        ),
    ),
    Case(
        group="persona",
        name="persona: student, tight budget, shared living",
        message=(
            "دانشجوام و بودجه‌ام خیلی کمه. دنبال یه اتاق یا خونه مشترک با هم‌خونه‌ای می‌گردم "
            "نزدیک دانشگاه تهران. نهایت ۵۰ پیش و ۴ تومن اجاره. ارزون بودنش از هر چیزی مهم‌تره."
        ),
        expect={"max_deposit": 50 * MILLION, "max_rent": 4 * MILLION, "living_kind": "shared"},
        judge=(
            "Cheapness is stated as the single most important thing ('از هر چیزی مهم‌تره'), so `budget` "
            "must dominate the weight vector (>=0.4)."
        ),
    ),
    Case(
        group="persona",
        name="persona: affluent family, full rahn, north Tehran",
        message=(
            "دنبال یه واحد بزرگ بالای ۱۵۰ متر تو زعفرانیه یا الهیه هستم، ترجیحا نوساز. "
            "رهن کامل می‌دم و اجاره ماهانه نمی‌خوام. کیفیت ساختمون و محله برام از قیمت مهم‌تره."
        ),
        expect={
            "min_area_sqm": 150,
            "full_rahn_only": True,
            "target_neighborhoods": ["زعفرانیه", "الهیه"],
            "financial_persona": "prefer_higher_deposit",
        },
        # "ترجیحا نوساز" is deliberately not asserted as min_build_year: it is a
        # preference, and turning a "preferably" into a hard filter would drop
        # older units this user said they would accept. It belongs in the
        # `freshness` weight, which is what the judge line asks for.
        judge=(
            "Quality of building and neighborhood explicitly outrank price: `quality` (and/or "
            "`freshness`) must be raised well above baseline and `budget` cut below it. "
            "'ترجیحا نوساز' should show up as freshness weight, not necessarily as a hard "
            "min_build_year."
        ),
    ),
    Case(
        group="persona",
        name="persona: remote worker, metro irrelevant, soft qualities",
        message=(
            "من دورکارم و کل روز خونه‌ام، برای همین نزدیکی به مترو اصلا برام مهم نیست. "
            "یه واحد ۶۰ تا ۸۰ متری آفتاب‌گیر و ساکت می‌خوام که یه گوشه‌ی دنجش بشه میز کار گذاشت. "
            "تا ۲۵۰ پیش."
        ),
        expect={"min_area_sqm": 60, "max_area_sqm": 80, "max_deposit": 250 * MILLION},
        judge=(
            "Metro closeness is explicitly dismissed -> commute_importance <= 0.3 and a small commute "
            "weight. The sunlit/quiet/work-corner qualities are soft preferences: soft_preferences must "
            "be populated and the `soft` weight raised (>=0.18)."
        ),
    ),
    Case(
        group="persona",
        name="persona: family with a car, schools, storage",
        message=(
            "خانواده چهار نفره‌ایم، ماشین داریم پس مترو مهم نیست ولی پارکینگ و انباری حتما لازمه. "
            "سه خوابه، تو نارمک یا تهرانپارس که مدرسه‌های خوب داره. ۶۰۰ پیش و ۱۰ اجاره، "
            "قیمت مناسب نسبت به محله برام مهمه."
        ),
        expect={
            "min_rooms": 3,
            "must_have_parking": True,
            "must_have_storage": True,
            "target_neighborhoods": ["نارمک", "تهرانپارس"],
            "max_deposit": 600 * MILLION,
            "max_rent": 10 * MILLION,
        },
        judge=(
            "'قیمت مناسب نسبت به محله' is the `value` criterion (price against that محله's own median), "
            "not plain `budget`: `value` must be raised above its 0.12 baseline. Metro is dismissed -> "
            "commute_importance <= 0.3."
        ),
    ),
]

# One message carrying the entire brief. The failure this catches is not
# mis-reading any single clause but dropping clauses: a model that gets eight
# of eleven fields right on a long message is unusable, because the user has
# no way to tell which three were lost.
KITCHEN_SINK: list[Case] = [
    Case(
        group="kitchen_sink",
        name="kitchen sink: everything in one breath",
        message=(
            "سلام. من و خانواده‌ام از کرج داریم میایم تهران و دنبال آپارتمان اجاره‌ای هستیم. "
            "بودجه‌مون ۵۰۰ میلیون ودیعه و ماهی ۲۰ تومن اجاره‌ست، تبدیل هم اوکیه. "
            "دو خوابه، بین ۹۰ تا ۱۲۰ متر، آسانسور و پارکینگ و انباری داشته باشه، بالکن هم باشه عالیه. "
            "ساختمون زیر ۱۰ سال ساخت باشه، طبقه اول به بالا، همکف نه. "
            "محله‌ها: سعادت‌آباد، شهرک غرب یا پونک. فقط آگهی‌های عکس‌دار رو نشونم بده. "
            "محل کارم میدان آرژانتینه و با مترو میرم، نهایت ۴۰ دقیقه راه باشه. "
            "از همه مهم‌تر اینکه نزدیک مترو باشه."
        ),
        expect={
            "max_deposit": 500 * MILLION,
            "max_rent": 20 * MILLION,
            "can_convert": True,
            "min_rooms": 2,
            "min_area_sqm": 90,
            "max_area_sqm": 120,
            "must_have_elevator": True,
            "must_have_parking": True,
            "must_have_storage": True,
            "must_have_balcony": True,
            "must_have_images": True,
            "min_build_year": (1393, 1397),
            "min_floor": (1, 1),
            "target_neighborhoods": ["سعادت‌آباد", "شهرک غرب", "پونک"],
            "commute_mode": "transit",
            "max_commute_mins": 40,
        },
        judge=(
            "'از همه مهم‌تر اینکه نزدیک مترو باشه' is a superlative about reachability: "
            "commute_importance >= 0.8 and the commute weight must be the largest in the vector."
        ),
    ),
    Case(
        group="kitchen_sink",
        name="kitchen sink: long, rambling, with negations",
        message=(
            "ببینید من یه چیز خاصی نمی‌خوام ولی چند تا شرط دارم. اول اینکه پارکینگ نمی‌خوام، "
            "ماشین ندارم و اصلا لازمش ندارم. آسانسور هم برام مهم نیست چون طبقه پایین می‌خوام، "
            "نهایت طبقه دو. زیرزمین و همکف هم نه. متراژ زیر ۷۵ متر باشه، تک خوابه هم اوکیه. "
            "پول پیش زیادی ندارم، نهایت ۱۵۰ تومن، ولی اجاره‌ش رو تا ۱۲ می‌تونم بدم. "
            "تو یوسف‌آباد یا امیرآباد. تبدیل هم نمی‌خوام، همون مبلغ آگهی."
        ),
        expect={
            "must_have_parking": False,
            "must_have_elevator": False,
            "max_floor": (2, 2),
            "min_floor": (1, 1),
            "max_area_sqm": 75,
            "min_rooms": 1,
            "max_deposit": 150 * MILLION,
            "max_rent": 12 * MILLION,
            "can_convert": False,
            "financial_persona": "prefer_higher_rent",
            "target_neighborhoods": ["یوسف‌آباد", "امیرآباد"],
        },
    ),
]

# The other end of the range: a message with almost nothing in it. Two things
# have to be right at once -- the extractor must invent nothing, and the reply
# must go and ask for what is missing instead of pretending to search.
SPARSE: list[Case] = [
    Case(
        group="sparse",
        name="sparse: bare greeting",
        message="سلام",
        expect={},
        forbid=("max_deposit", "max_rent", "min_area_sqm", "min_rooms", "target_neighborhoods", "weights"),
        reply_judge=(
            "The user has said only 'سلام'. A good reply greets them briefly and asks what they are "
            "looking for -- ideally budget or محله. It must be Persian, warm, short (1-3 sentences), "
            "must not claim to have found or searched anything, and must not invent listings."
        ),
    ),
    Case(
        group="sparse",
        name="sparse: 'I want a house'",
        message="خونه می‌خوام",
        expect={},
        forbid=("max_deposit", "max_rent", "min_area_sqm", "min_rooms", "target_neighborhoods"),
        reply_judge=(
            "Almost no information given. The reply must ask for the essentials (budget and/or محله and "
            "size) in one short, natural Persian question -- not a numbered questionnaire, and not a "
            "claim that results were found."
        ),
    ),
    Case(
        group="sparse",
        name="sparse: vague 'somewhere good'",
        message="یه جای خوب می‌خوام، چی پیشنهاد می‌دی؟",
        expect={},
        forbid=("max_deposit", "max_rent", "target_neighborhoods", "min_area_sqm"),
        reply_judge=(
            "'یه جای خوب' is not a filter. The reply must ask what 'خوب' means to them (budget, محله, "
            "commute) rather than naming specific neighborhoods out of thin air or fabricating listings."
        ),
    ),
    Case(
        group="sparse",
        name="sparse: budget only, no numbers",
        message="بودجه‌ام کمه",
        expect={},
        forbid=("max_deposit", "max_rent", "min_area_sqm", "target_neighborhoods"),
        judge=(
            "A statement that money is tight and nothing else: raising `budget` in the weights is "
            "correct, but no numeric ceiling may be invented. Judge only whether the emphasis on price "
            "was read without fabricating figures."
        ),
        reply_judge=(
            "The user said only that their budget is small. The reply must ask for the actual numbers "
            "(ودیعه / اجاره) politely and briefly, in Persian."
        ),
    ),
    Case(
        group="sparse",
        name="sparse: one word follow-up",
        history=[
            {"role": "user", "content": "دنبال خونه‌ام"},
            {"role": "assistant", "content": "حتما! بودجه و محله مورد نظرتان را بفرمایید."},
        ],
        message="نمی‌دونم",
        expect={},
        forbid=("max_deposit", "max_rent", "target_neighborhoods", "min_area_sqm"),
        reply_judge=(
            "The user does not know where to start. A good reply helps them narrow down -- offering a "
            "concrete way in (e.g. asking about workplace, or roughly how much they can pay) -- "
            "without lecturing, in short natural Persian."
        ),
    ),
]


JUDGE_PROMPT = """You are grading an intent-extraction model for a Persian (Iranian) rental-search \
product. You are given the user's message (and prior turns), what the grader expected about the \
*emphasis* of the request, and the JSON the model produced.

Judge ONLY the emphasis-related fields: `weights` (budget, value, area, amenity, commute, \
freshness, soft), `commute_importance`, `financial_persona`, `soft_preferences` and \
`soft_preference_summary`. Ignore hard filters such as prices, area and neighborhoods -- those \
are checked separately.

Reply with ONE JSON object: {"score": 0-5, "reason": "<one short English sentence>"}
5 = the emphasis is read correctly and the weights clearly reflect it.
3 = directionally right but weak or partially applied.
0 = the emphasis is missing or inverted."""


REPLY_JUDGE_PROMPT = """You are grading the conversational reply of a Persian-speaking Tehran \
rental-search assistant. You are given the prior turns, the user's latest message, what a good \
reply should do, and the reply the assistant produced.

Grade the reply as a piece of conversation, not as data extraction. Penalise: non-Persian or \
broken Persian, robotic or templated phrasing, markdown, replies longer than about three \
sentences, questionnaires, claiming to have found or searched listings that do not exist, \
inventing neighborhoods or prices the user never mentioned, and failing to ask for the missing \
information when the request is too vague to search on.

Reply with ONE JSON object: {"score": 0-5, "asked_for_missing_info": true|false, \
"reason": "<one short English sentence>"}"""


_DEFAULTS = ExtractedSearchIntent()


# Messages taken from, or shaped like, what real users actually type: a whole
# brief in one breath, place names that are landmarks rather than محله, a
# workplace given by name, a misspelling, and a preference stated in passing at
# the end. Every case here comes from an observed failure.
WILD: list[Case] = [
    Case(
        group="wild",
        name="landmarks + workplace by name + pay-less preference",
        message=(
            "در محدوده تاتر شهر و انقلاب دنبال یخونه با دو اتاق و أسانسور و حداقل 70 متر زیربنا میگردم. "
            "محل کارم توی دانشگاه شریفه و با مترو میرم سر کار. حداکثر 800 ملیون میتونم رهن بدم و 40 اجاره. "
            "ترجیم اینه که پول کمتری بدم"
        ),
        expect={
            "min_rooms": 2,
            "must_have_elevator": True,
            "min_area_sqm": 70,
            "max_deposit": 800 * MILLION,
            "max_rent": 40 * MILLION,
            "commute_mode": "transit",
            # The area has to land on the انقلاب/تئاتر شهر blocks. Key 655 is
            # فلسطین (میدان انقلاب); before the gazetteer, "انقلاب" resolved to
            # بهارستان, two kilometres east, on a street-name keyword.
            "target_neighborhood_keys": ["655"],
            # دانشگاه شریف, geocoded from the name the user gave.
            "workplace_lat": (35.69, 35.72),
            "workplace_lon": (51.34, 51.37),
        },
        # "پول کمتری بدم" says nothing about the deposit/rent split, so reading
        # it as a persona pushes the user toward a bigger deposit they never
        # asked for.
        forbid=("financial_persona", "full_rahn_only", "must_have_parking"),
        judge=(
            "Gave hard ceilings AND said they would rather pay less: budget must be the largest "
            "weight (>=0.35). A workplace was named and they commute by metro, so commute_importance "
            "should be >=0.6 -- but naming a workplace is not a claim that the commute outranks the "
            "price, so a commute weight near its 0.14 baseline is correct here, not a fault."
        ),
        reply_judge=(
            "Should confirm the area, the two-bedroom/elevator/70m requirements, the budget and that "
            "it will favour cheaper options. It must not claim to prefer a lower rent and a higher "
            "deposit -- the user never said that."
        ),
    ),
    Case(
        group="wild",
        name="workplace only, commute ceiling",
        message="شرکتم تو میدون ونکه، حداکثر ۲۰ دقیقه راه باشه تا سر کار",
        expect={"max_commute_mins": 20, "workplace_lat": (35.74, 35.77), "workplace_lon": (51.39, 51.43)},
        forbid=("max_deposit", "max_rent", "min_rooms", "target_neighborhoods"),
        judge=(
            "A workplace with a tight commute ceiling: commute_importance should be high (>=0.6) and "
            "the commute weight should sit above its 0.14 baseline. Nothing else was stated, so every "
            "other criterion staying near baseline is correct."
        ),
    ),
    Case(
        group="wild",
        name="hospital workplace, drives",
        message="پرستارم و بیمارستان میلاد کار می‌کنم، با ماشین میرم. یه واحد ۶۰ متری دو خوابه می‌خوام",
        expect={
            "commute_mode": "drive",
            "min_area_sqm": 60,
            "min_rooms": 2,
            "workplace_lat": (35.72, 35.75),
            "workplace_lon": (51.36, 51.40),
        },
        forbid=("living_kind", "must_have_parking"),
    ),
    Case(
        group="wild",
        name="two landmark areas, no محله named",
        message="خونه‌ای نزدیک میدان آرژانتین یا حوالی پارک ملت می‌خوام، ۱۵۰ پیش و ۱۲ اجاره",
        # [""] asserts only that *something* resolved: which polygons a
        # landmark expands to is the resolver's business, but a landmark-only
        # message resolving to nothing means the user's area was thrown away.
        expect={"max_deposit": 150 * MILLION, "max_rent": 12 * MILLION, "target_neighborhood_keys": [""]},
        forbid=("min_rooms",),
    ),
    Case(
        group="wild",
        name="pay-less preference next to a figure",
        message="۵۰۰ رهن دارم، ولی اگه بشه کمتر بدم خیلی بهتره",
        expect={"max_deposit": 500 * MILLION},
        forbid=("financial_persona", "full_rahn_only"),
        judge=(
            "A ceiling plus a wish to spend less: budget should be the largest weight, at 0.35 or "
            "more of the vector. "
            "financial_persona must stay balanced -- nothing was said about the deposit/rent split."
        ),
    ),
    Case(
        group="wild",
        name="workplace and search area are different places",
        message="دنبال خونه تو نارمکم، ولی محل کارم دانشگاه شریفه، ۳۰۰ پیش",
        expect={
            "target_neighborhoods": ["نارمک"],
            "max_deposit": 300 * MILLION,
            "workplace_lat": (35.69, 35.72),
            "workplace_lon": (51.34, 51.37),
        },
    ),
]


def _check(intent: ExtractedSearchIntent, expect: dict[str, Any]) -> list[str]:
    failures = []
    for field_name, expected in expect.items():
        actual = getattr(intent, field_name)
        if isinstance(expected, tuple):
            ok = actual is not None and expected[0] <= actual <= expected[1]
        elif isinstance(expected, list):
            # Order-insensitive, and a superset is fine: the model naming an
            # extra place the user mentioned is not an error.
            ok = actual is not None and all(any(e in a for a in actual) for e in expected)
        else:
            ok = actual == expected
        if not ok:
            failures.append(f"{field_name}={actual!r} (expected {expected!r})")
    return failures


def _check_forbidden(intent: ExtractedSearchIntent, forbid: tuple[str, ...]) -> list[str]:
    """Fields the user never mentioned must come back untouched.

    Checked against the model's own defaults rather than against None, so a
    fabricated `must_have_parking: true` counts the same as a fabricated
    budget: both quietly narrow the search on the user's behalf.
    """
    failures = []
    for name in forbid:
        actual = getattr(intent, name)
        if actual != getattr(_DEFAULTS, name):
            failures.append(f"{name}={actual!r} invented (expected default)")
    return failures


async def _reply(client: OpenRouterClient, case: Case) -> str:
    chunks = []
    async for token in stream_chat_reply(client, case.message, case.history or None):
        chunks.append(token)
    return "".join(chunks).strip()


async def _judge(client: OpenRouterClient, case: Case, intent: ExtractedSearchIntent) -> dict[str, Any]:
    payload = {
        "prior_turns": case.history,
        "user_message": case.message,
        "expected_emphasis": case.judge,
        "model_output": intent.model_dump(
            include={"weights", "commute_importance", "financial_persona", "soft_preferences", "soft_preference_summary"}
        ),
    }
    try:
        return await client.chat_completion(
            [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            json_mode=True,
        )
    except Exception as error:  # a judge outage must not look like a model failure
        return {"score": None, "reason": f"judge unavailable: {type(error).__name__}"}


async def _judge_reply(client: OpenRouterClient, case: Case, reply: str) -> dict[str, Any]:
    payload = {
        "prior_turns": case.history,
        "user_message": case.message,
        "what_a_good_reply_does": case.reply_judge,
        "assistant_reply": reply,
    }
    try:
        return await client.chat_completion(
            [
                {"role": "system", "content": REPLY_JUDGE_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            json_mode=True,
        )
    except Exception as error:
        return {"score": None, "reason": f"judge unavailable: {type(error).__name__}"}


@dataclass
class Result:
    case: Case
    fields_total: int = 0
    fields_failed: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    emphasis_score: Optional[int] = None
    emphasis_reason: str = ""
    reply: str = ""
    reply_score: Optional[int] = None
    reply_asked: Optional[bool] = None
    reply_reason: str = ""
    error: str = ""
    # The extracted object itself, kept in the report: a failure that only
    # says "budget weight too low" is not actionable without the vector.
    intent: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.error or self.fields_failed or self.invented)


async def _run_case(client: OpenRouterClient, case: Case) -> Result:
    result = Result(case=case, fields_total=len(case.expect) + len(case.forbid))
    try:
        intent = await extract_search_intent(client, case.message, case.history or None)
    except Exception as error:
        # A failed call is not a free pass: every field the case was going to
        # assert counts as missed, or an outage would read as a perfect run.
        result.error = f"{type(error).__name__}: {error}"
        result.fields_failed = [f"{name}: not extracted ({type(error).__name__})" for name in case.expect]
        result.invented = []
        return result

    result.intent = intent.model_dump(exclude_defaults=True)
    result.fields_failed = _check(intent, case.expect)
    result.invented = _check_forbidden(intent, case.forbid)

    if case.judge:
        verdict = await _judge(client, case, intent)
        score = verdict.get("score")
        result.emphasis_score = int(score) if isinstance(score, (int, float)) else None
        result.emphasis_reason = str(verdict.get("reason", ""))

    if case.reply_judge:
        try:
            result.reply = await _reply(client, case)
        except Exception as error:
            result.reply_reason = f"reply generation failed: {type(error).__name__}"
        else:
            verdict = await _judge_reply(client, case, result.reply)
            score = verdict.get("score")
            result.reply_score = int(score) if isinstance(score, (int, float)) else None
            result.reply_asked = verdict.get("asked_for_missing_info")
            result.reply_reason = str(verdict.get("reason", ""))
    return result


async def run(cases: list[Case], concurrency: int = 2, out: Optional[str] = None) -> None:
    """Run every case and print a per-case then per-group report.

    Cases run concurrently -- the harness is entirely I/O-bound on the provider,
    and a serial pass over forty cases with two judge calls each takes minutes.
    Results are collected in order so the printed report stays stable between
    runs, which is what makes two runs diffable.
    """
    client = OpenRouterClient()
    gate = asyncio.Semaphore(concurrency)

    async def guarded(case: Case) -> Result:
        async with gate:
            return await _run_case(client, case)

    try:
        results = await asyncio.gather(*(guarded(case) for case in cases))
    finally:
        await client.close()

    for result in results:
        mark = "\u2713" if result.ok else "\u2717"
        print(f"{mark} [{result.case.group}] {result.case.name}")
        if result.error:
            print(f"    extraction failed -- {result.error}")
        for failure in result.fields_failed:
            print(f"    field: {failure}")
        for invention in result.invented:
            print(f"    invented: {invention}")
        if result.emphasis_score is not None or result.emphasis_reason:
            print(f"    emphasis: {result.emphasis_score}/5 -- {result.emphasis_reason}")
        if result.case.reply_judge:
            print(f"    reply: {result.reply_score}/5 asked={result.reply_asked} -- {result.reply_reason}")
            print(f"      \u00ab{result.reply}\u00bb")

    print()
    groups = sorted({result.case.group for result in results})
    for group in groups:
        rows = [result for result in results if result.case.group == group]
        total = sum(row.fields_total for row in rows)
        failed = sum(len(row.fields_failed) + len(row.invented) for row in rows)
        emphasis = [row.emphasis_score for row in rows if row.emphasis_score is not None]
        replies = [row.reply_score for row in rows if row.reply_score is not None]
        line = f"{group:<12} cases {sum(1 for row in rows if row.ok)}/{len(rows)} clean"
        if total:
            line += f" | fields {total - failed}/{total}"
        if emphasis:
            line += f" | emphasis {sum(emphasis) / len(emphasis):.1f}/5"
        if replies:
            line += f" | reply {sum(replies) / len(replies):.1f}/5"
        print(line)

    total = sum(row.fields_total for row in results)
    failed = sum(len(row.fields_failed) + len(row.invented) for row in results)
    emphasis = [row.emphasis_score for row in results if row.emphasis_score is not None]
    replies = [row.reply_score for row in results if row.reply_score is not None]
    print()
    print(f"structured fields: {total - failed}/{total} correct")
    if emphasis:
        print(f"emphasis judge:    {sum(emphasis) / len(emphasis):.2f}/5 over {len(emphasis)} cases")
    if replies:
        print(f"reply judge:       {sum(replies) / len(replies):.2f}/5 over {len(replies)} cases")

    if out:
        payload = [
            {
                "group": row.case.group,
                "name": row.case.name,
                "ok": row.ok,
                "error": row.error,
                "field_failures": row.fields_failed,
                "invented": row.invented,
                "emphasis_score": row.emphasis_score,
                "emphasis_reason": row.emphasis_reason,
                "reply": row.reply,
                "reply_score": row.reply_score,
                "reply_reason": row.reply_reason,
                "intent": row.intent,
            }
            for row in results
        ]
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"\nreport written to {out}")


GROUPS = {
    "single": SINGLE_TURN,
    "multi": MULTI_TURN,
    "persona": PERSONAS,
    "kitchen_sink": KITCHEN_SINK,
    "sparse": SPARSE,
    "wild": WILD,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="single-turn cases only")
    parser.add_argument("--group", action="append", choices=sorted(GROUPS), help="run only these groups")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--out", help="write a JSON report here")
    args = parser.parse_args()

    if args.quick:
        selected = list(SINGLE_TURN)
    elif args.group:
        selected = [case for group in args.group for case in GROUPS[group]]
    else:
        selected = [case for group in GROUPS.values() for case in group]
    asyncio.run(run(selected, concurrency=args.concurrency, out=args.out))


if __name__ == "__main__":
    main()
