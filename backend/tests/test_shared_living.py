"""app.core.shared_living -- keeping room and bed adverts out of the cheap tail.

The module's docstring records which phrases were kept and which were measured
and rejected; the rejections are the interesting half, since a classifier that
fires on مجردی would quietly drop ordinary apartments out of every search.
"""

import pytest

from app.core.shared_living import is_shared_living


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
