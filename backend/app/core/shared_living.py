"""Telling a shared home or a dormitory apart from a whole property to rent.

Divar files هم‌خانه adverts, room lettings and dormitory beds under the same
``apartment-rent`` category as whole apartments -- there is no field on the
advert that separates them. They are nonetheless a different product: someone
offering a room in a flat they live in, or a bed in a dormitory, quotes a
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


def is_shared_living(title: str | None, description: str | None) -> bool:
    """True when the advert is offering a room, a bed or a flatmate slot."""
    blob = f"{normalize_persian_text(title or '')} {normalize_persian_text(description or '')}"
    # Zero-width joiners survive normalisation but split "هم‌خانه" for the
    # regex, so they collapse into the ordinary space the patterns expect.
    return bool(_MARKERS.search(re.sub(r"[‌\s]+", " ", blob)))
