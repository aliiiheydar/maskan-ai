"""Telling a whole home to rent from everything else filed beside it.

Two things are not a home you rent and live in on your own, and Divar files
both under the same ``apartment-rent`` category as whole apartments: a room,
bed or flatmate slot (below), and a parking space. They are separated here so
the search can treat them as their own market, and the app offers them under
one option -- هم‌خانه و خوابگاه -- rather than mixing them into ordinary
results where they read as impossibly cheap flats.

A room or a bed is a different product, not a bargain: someone offering a
room in a flat they live in, or a bed in a dormitory, quotes a
fraction of a whole-apartment price, so these dominate the cheap tail of every
search and make an ordinary rental look overpriced beside them. The search has
to treat them as a separate market rather than as bargains.

With no field to read, the signal is in the advertiser's own words, and the
rule below was derived by reading the cheap tail of an 18,800-listing corpus:

* ``هم‌خانه`` / ``هم‌خونه`` and the ``هم‌اتاقی`` / ``هم‌منزل`` family -- 244 of
  the 265 matches, and the phrase people actually use for "flatmate wanted";
* ``خوابگاه`` and ``پانسیون`` -- dormitories and boarding houses;
* letting a *room* rather than a unit: ``اجاره اتاق``, ``اتاق مبله``,
  ``یک اتاق ۳۰ متری``;
* letting a *bed*: ``اجاره تخت``, ``رزرو تخت``.

Two things were deliberately left out after measuring them. ``مجردی`` ("suits
singles") and ``فقط خانم`` describe who a *whole* unit is offered to, and
matched ordinary apartments almost every time. A second tier of weaker hints
(``دانشجویی``, ``اشتراکی``, ``هر نفر``) added three listings when required in
pairs, two of which were ordinary apartments -- not worth the precision.

The bare ``هم اتاق`` spelling is excluded on purpose: "هم سالن هم اتاق‌ها
نورگیر" is a sentence about an ordinary flat, so the ی of ``هم‌اتاقی`` is
required.
"""

from __future__ import annotations

import re

from app.core.normalizers import normalize_persian_text

_MARKERS = re.compile(
    r"هم\s?خانه|هم\s?خونه|هم\s?اتاقی|هم\s?منزل|هم\s?سکونت"
    r"|خوابگاه|پانسیون"
    r"|اجاره\s?(?:ی\s?)?(?:یک\s?)?اتاق|اتاق\s?(?:برای\s?)?اجاره"
    r"|یک\s?اتاق\s?\d+\s?متر|اتاق\s?مبله"
    r"|اجاره\s?تخت|رزرو\s?تخت|تخت\s?خواب\s?اجاره"
)


# A parking space let on its own. The word پارکینگ is useless by itself --
# 1,534 of 21,377 titles carry it and all but a few dozen are apartments
# advertising a parking spot they come with -- so what is matched is پارکینگ
# as the *subject* of the advert rather than as one of its features:
#
#   * a letting verb running into it: "اجاره پارکینگ", "رهن پارکینگ", and the
#     same with a few words in between ("اجاره سالیانه و ماهانه پارکینگ",
#     "اجاره یک جای پارکینگ", "اجاره ۲ تا پارکینگ غیرمزاحم");
#   * the title opening on it: "پارکینگ مسقف", "پارکینگ خودرو و موتور";
#   * the reverse order: "پارکینگ اجاره‌ای".
#
# پارکینک, with a ک, is included: it is a real misspelling in the corpus and
# the advert is no less a parking space for it.
_PARKING_MARKERS = re.compile(
    r"(?:^|[\s/،,\-])(?:اجاره|رهن|کرایه|واگذاری)\s*(?:\S+\s+){0,3}?پارکین[گک]"
    r"|^\s*پارکین[گک]"
    r"|پارکین[گک]\s*(?:اجاره|کرایه)"
)

# ...unless the same title also advertises a dwelling. An apartment whose
# title happens to lead with its parking ("پارکینگ اصلی ۶۴ متر طبقه دوم") is a
# flat, and so is anything quoting a floor area: a parking space is sold as a
# place to put a car, never as square metres. This costs two genuine parking
# adverts out of ~54 and keeps hundreds of apartments out, which is the trade
# worth making -- a home wrongly filed as parking disappears from the search
# it belongs in, while parking wrongly left in merely looks cheap.
_DWELLING_MARKERS = re.compile(
    r"خواب|آپارتمان|اپارتمان|سوییت|سوئیت|مغازه|دفتر|طبقه|واحد(?![یي])|منزل|ویلا|خانه|اتاق|متری|متر\b"
)


def _one_line(*parts: str | None) -> str:
    """The advert's words, normalised and flattened onto one line.

    Zero-width joiners survive normalisation but split "هم‌خانه" for the
    regexes, so they collapse into the ordinary space the patterns expect.
    """
    blob = " ".join(normalize_persian_text(part or "") for part in parts)
    return re.sub(r"[‌\s]+", " ", blob)


def is_shared_living(title: str | None, description: str | None) -> bool:
    """True when the advert is offering a room, a bed or a flatmate slot."""
    return bool(_MARKERS.search(_one_line(title, description)))


def is_parking_rental(title: str | None) -> bool:
    """True when the advert is letting a parking space rather than a home.

    The title only. Descriptions name parking constantly -- it is one of the
    first amenities anyone lists -- so reading them would flag a large part of
    the corpus, while an advertiser letting a parking space says so in the
    title every time.
    """
    text = _one_line(title)
    return bool(_PARKING_MARKERS.search(text)) and not _DWELLING_MARKERS.search(text)


def is_not_a_home(title: str | None, description: str | None) -> bool:
    """True for anything that is not a whole property to live in.

    The one predicate the corpus is flagged with, so the crawler and the
    migration cannot drift apart on what belongs in the standard search.
    """
    return is_shared_living(title, description) or is_parking_rental(title)
