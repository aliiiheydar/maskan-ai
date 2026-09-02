"""app.core.shared_living -- keeping room and bed adverts out of the cheap tail.

The module's docstring records which phrases were kept and which were measured
and rejected; the rejections are the interesting half, since a classifier that
fires on مجردی would quietly drop ordinary apartments out of every search.
"""

import pytest

from app.core.shared_living import is_not_a_home, is_parking_rental, is_shared_living


@pytest.mark.parametrize(
    "text",
    [
        "هم‌خانه خانم نیازمندیم",
        "هم خونه برای آپارتمان دو خوابه",
        "جذب هم‌اتاقی دانشجو",
        "خوابگاه دخترانه نزدیک دانشگاه",
        "پانسیون مجهز با صبحانه",
        "اجاره اتاق مبله در آپارتمان",
        "اجاره‌ی یک اتاق ۳۰ متری",
        "رزرو تخت به صورت ماهانه",
    ],
)
def test_room_bed_and_flatmate_adverts_are_caught(text):
    assert is_shared_living(text, None)


@pytest.mark.parametrize(
    "text",
    [
        "آپارتمان ۸۵ متری دو خوابه با آسانسور",
        # Measured and deliberately not a marker: both describe who a *whole*
        # unit is offered to, and matched ordinary apartments almost every time.
        "مناسب مجردی، فول امکانات",
        "فقط خانم، واحد ۶۰ متری",
        # The bare "هم اتاق" spelling, in the sentence that made it a false
        # positive -- the ی of هم‌اتاقی is what carries the meaning.
        "هم سالن هم اتاق‌ها نورگیر است",
        # Single weak hints, which were shown not to pay for themselves.
        "منطقه دانشجویی و پر رفت‌وآمد",
    ],
)
def test_ordinary_apartments_are_left_alone(text):
    assert not is_shared_living(text, None)


def test_the_description_is_read_as_well_as_the_title():
    assert is_shared_living("آپارتمان ۷۰ متری", "برای هم‌خانه شدن با یک نفر دیگر")


def test_arabic_spellings_are_normalised_before_matching():
    """Divar text arrives with Arabic ي/ك mixed in; the classifier normalises
    first, so the same advert cannot slip through on its keyboard layout."""
    assert is_shared_living("هم‌خانه ميخواهيم", None)


def test_an_advert_with_no_text_at_all_is_not_shared_living():
    assert not is_shared_living(None, None)


@pytest.mark.parametrize(
    "title",
    [
        "اجاره پارکینگ",
        "اجاره پارکینگ مسقف",
        "پارکینگ اجاره ای در جوادیه",
        "رهن پارکینگ خودرو نزدیک مترو شهرری",
        "پارکینگ خودرو و موتور",
        # Words between the letting verb and the noun.
        "اجاره سالیانه و ماهانه پارکینگ",
        "اجاره یک جای پارکینگ",
        # A real misspelling in the corpus; the advert is no less a parking
        # space for it.
        "اجاره پارکینک",
    ],
)
def test_a_parking_space_let_on_its_own_is_caught(title):
    assert is_parking_rental(title)


@pytest.mark.parametrize(
    "title",
    [
        # The word alone means nothing: 1,534 of 21,377 titles carry it and
        # nearly all are flats advertising the spot they come with.
        "آپارتمان 70 متری با پارکینگ و انباری",
        "اجاره آپارتمان 45متری پارکینگ دار",
        "70متر پارکینگدار عربی",
        "اجاره 54 متر بدون پارکینگ واسانسور",
        # Leads with the amenity, but a floor and an area give it away.
        "پارکینگ اصلی 64 متر طبقه دوم",
    ],
)
def test_a_flat_that_merely_has_parking_is_left_alone(title):
    assert not is_parking_rental(title)


def test_the_description_is_not_read_for_parking():
    """Every other advert names parking in its description; an advertiser
    letting one says so in the title."""
    assert not is_parking_rental(None)
    assert not is_not_a_home("آپارتمان ۷۰ متری دو خوابه", "دارای پارکینگ و انباری و آسانسور")


def test_one_predicate_covers_everything_that_is_not_a_whole_home():
    """The crawler and the migration both flag on this, so they cannot drift
    apart on what belongs in the standard search."""
    assert is_not_a_home("اجاره پارکینگ مسقف", None)
    assert is_not_a_home("هم‌خانه خانم نیازمندیم", None)
    assert not is_not_a_home("آپارتمان ۸۵ متری دو خوابه با آسانسور", None)
