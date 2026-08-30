import pytest
from app.services.pdf.number_parser import NumberTokenParser


def test_number_token_parser_arabic():
    assert NumberTokenParser.parse_token("1") == "1"
    assert NumberTokenParser.parse_token("25") == "25"
    assert NumberTokenParser.parse_token("102") == "102"
    assert NumberTokenParser.parse_token("1.1") == "1.1"
    assert NumberTokenParser.parse_token("3.4.2") == "3.4.2"
    assert NumberTokenParser.to_int("25") == 25
    assert NumberTokenParser.to_int("2.1") == 2


def test_number_token_parser_roman():
    assert NumberTokenParser.parse_token("I") == "1"
    assert NumberTokenParser.parse_token("IV") == "4"
    assert NumberTokenParser.parse_token("IX") == "9"
    assert NumberTokenParser.parse_token("XIV") == "14"
    assert NumberTokenParser.parse_token("XXI") == "21"
    assert NumberTokenParser.parse_token("L") == "50"
    assert NumberTokenParser.parse_token("xc") == "90"
    assert NumberTokenParser.to_int("XIV") == 14


def test_number_token_parser_words():
    assert NumberTokenParser.parse_token("One") == "1"
    assert NumberTokenParser.parse_token("Two") == "2"
    assert NumberTokenParser.parse_token("Twelve") == "12"
    assert NumberTokenParser.parse_token("twenty-one") == "21"
    assert NumberTokenParser.parse_token("Thirty Four") == "34"
    assert NumberTokenParser.parse_token("one hundred and five") == "105"
    assert NumberTokenParser.to_int("twenty-one") == 21


def test_number_token_parser_invalid():
    assert NumberTokenParser.parse_token("") is None
    assert NumberTokenParser.parse_token("XYZ") is None
    assert NumberTokenParser.to_int("invalid_token") is None
