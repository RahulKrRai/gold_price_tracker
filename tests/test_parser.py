import pytest

from goldtracker.parser import parse_title

# Real titles seen on Amazon and Myntra on 2026-10-16
CASES = [
    ("PNG Jewellers 2.5 gram Vedhani Gold Ring 24 kt (995)", 2.5, 0.995, "ring"),
    ("WHP Jewellers 24kt (999) 2 gram OM Yellow Gold Om Pendant", 2, 0.999, "pendant"),
    ("MMTC PAMP 24K 999.9 Purest Rose Engraved Gold Pendant, 2 Gram gold bar & coin, LBMA Certified", 2, 0.9999, "bar"),
    ("Kalyan Jewellers 24K (999) Purity Ayodhya Gold Coin Pendant 2 Gms", 2, 0.999, "coin"),
    ("Kalyan Jewellers 24KT 999 Lotus Gold Bar Coin - 3 g", 3, 0.999, "bar"),
    ("Kalyan Jewellers 24K Gold Ayodhya Coin -10gm", 10, 0.999, "coin"),
    ("Kalyan Jewellers 24K 999 Purity OHM Round Shaped Coin - 5g", 5, 0.999, "coin"),
    ("P.N.Gadgil Jewellers 1 gm Vedhani Gold Ring 24 kt (995)", 1, 0.995, "ring"),
    ("P.C Chandra Jewellers 22kt(916) Yellow Gold Coin Cum Pendant - 2 Gram", 2, 0.916, "coin"),
    ("BHIMA BIS Hallmark 22K 916 Purity Lakshmi Gold Coin 8 gram", 8, 0.916, "coin"),
    ("Kalyan Jewellers 22K 916 Purity Round Shaped Coin - 10g", 10, 0.916, "coin"),
    ("Zen Diamond India 24KT 999 Fine Gold Brand Logo Round Coin - 0.5 g", 0.5, 0.999, "coin"),
    ("Malabar Gold & Diamonds Laxmi 999 Purity 24KT Gold Coin Cum Pendant - 1.5g", 1.5, 0.999, "coin"),
    ("BHIMA Set Of 2 24K 999 Purity Gold Bar 2g+1g", 3, 0.999, "bar"),
    ("BHIMA BIS Hallmark 22K 916 Purity Lakshmi Gold Coin Combo 4g+2g", 6, 0.916, "coin"),
    ("WHP Jewellers 999 Yellow Gold OM Pendant Combo, 3 gram (2 Gm + 1 Gm)", 3, 0.999, "pendant"),
    ("Muthoot PAPPACHAN Swarnavarsham 24K (999) Combo Gold Oval Lakshmi Pendant 3 Gram (1gm each x 3 Pcs)",
     3, 0.999, "pendant"),
    ("Bangalore Refinery 24k (999) Purity 2.5 Gm Yellow Gold OM Round Pendant (without hook)", 2.5, 0.999, "pendant"),
    ("Augmont 24Kt (999) 1 Gram Gold Coin, pack of 2, 1 gram each", 2, 0.999, "coin"),
    ("Generic 10 Grams 24 Carat Gold Biscuit", 10, 0.999, "bar"),
]


@pytest.mark.parametrize("title,weight,purity,form", CASES)
def test_parse(title, weight, purity, form):
    p = parse_title(title)
    assert p.weight_g == pytest.approx(weight), title
    assert p.purity == pytest.approx(purity), title
    assert p.form == form, title
    assert not p.excluded


def test_pack_each_outside_parens():
    assert parse_title("SafeGold 24K Gold Coin 0.5 gram each, pack of 4").weight_g == pytest.approx(2.0)


def test_unknown_weight_and_purity():
    p = parse_title("Gold coin gift for Diwali")
    assert p.weight_g is None and p.purity is None and p.fine_grams is None


def test_does_not_read_karat_as_weight():
    assert parse_title("24 kt Gold Lakshmi Coin").weight_g is None


@pytest.mark.parametrize("title", [
    "1 Gram Gold Plated Lakshmi Coin",
    "Imitation Gold Coin 10g",
    "Micro Gold Plated 24K Ganesh Coin 5 gram",
])
def test_excludes_non_bullion(title):
    assert parse_title(title).excluded


def test_fine_grams():
    assert parse_title("Kalyan 22K 916 Coin 10 g").fine_grams == pytest.approx(9.16)


# Real Myntra titles seen on 2026-10-16
@pytest.mark.parametrize("title,weight", [
    ("Angara 24KT (999) 2+2 GM Combo Lakshmi Gold Coin", 4),
    ("Angara 24KT (999) 2+1 GM Combo Lakshmi Gold Coin", 3),
    ("PARSHWA PADMAVATI GOLD Happy Wedding Var Vadhu Jodi Design 999 Gold Coin - 50 mg", 0.05),
    ("PARSHWA PADMAVATI GOLD (999) 24KT Gold Coin- 0.025g", 0.025),
    ("PMJ Jewels Goddess Lakshmi 22KT Gold Coin- 0.500 gm", 0.5),
    ("C KRISHNIAH CHETTY JEWELLERS PVT LTD Set Of 2 24Kt Gold Coin-2g", 2),
    ("Mia by Tanishq 0.5 Gram 24 Karat Tulsi Gold Coin", 0.5),
])
def test_myntra_weights(title, weight):
    assert parse_title(title).weight_g == pytest.approx(weight)


@pytest.mark.parametrize("title", [
    "White Mango Decor Brass Coin",
    "Divine Solitaires 0.18ct Diamond Studded 22kt Gold Coin 3gm",
    "Designs & You Gold-Plated Bar-Shaped Necklace",
    "Accessorize London Green & Gold-Toned Brass T Bar & Coin Charm Necklace",
])
def test_excludes_myntra_non_bullion(title):
    assert parse_title(title).excluded


def test_brand_with_diamond_in_name_is_not_excluded():
    assert not parse_title("Zen Diamond India 24 KT Gold Coin- 5 gm").excluded
    assert not parse_title("Malabar Gold & Diamonds 24KT 999 Purity Rose Gold Bar - 5 g").excluded
