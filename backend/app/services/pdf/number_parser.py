import re
from typing import Optional

# Base English word number mappings
ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

SCALES = {
    "hundred": 100,
    "thousand": 1000,
}

ROMAN_NUMERALS = {
    "I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000
}


class NumberTokenParser:
    """
    Reusable parser that converts arbitrary Arabic, Roman, English word,
    and dotted numerical tokens into canonical string representations and integer values.
    Imposes no artificial maximum limits.
    """

    @classmethod
    def words_to_int(cls, text: str) -> Optional[int]:
        """Convert English words (e.g. 'twenty-five', 'one hundred and two') to integer."""
        clean = re.sub(r"[^a-zA-Z\s\-]", " ", text.lower())
        tokens = [t.strip() for t in re.split(r"[\s\-]+", clean) if t.strip() and t.strip() != "and"]
        if not tokens:
            return None

        total = 0
        current = 0

        for token in tokens:
            if token in ONES:
                current += ONES[token]
            elif token in TENS:
                current += TENS[token]
            elif token in SCALES:
                scale = SCALES[token]
                current = (current if current != 0 else 1) * scale
                if scale >= 1000:
                    total += current
                    current = 0
            else:
                return None

        return total + current

    @classmethod
    def roman_to_int(cls, roman: str) -> Optional[int]:
        """Convert Roman numeral string (e.g. 'IV', 'XXI', 'XIV') to integer."""
        roman = roman.strip().upper()
        if not roman or not re.match(r"^[IVXLCDM]+$", roman):
            return None

        total = 0
        prev_val = 0
        for char in reversed(roman):
            val = ROMAN_NUMERALS.get(char, 0)
            if val < prev_val:
                total -= val
            else:
                total += val
                prev_val = val
        return total if total > 0 else None

    @classmethod
    def parse_token(cls, raw_token: str) -> Optional[str]:
        """
        Normalize any numerical token (Arabic digits, Roman numerals, English words, dotted numbers)
        into a canonical clean string representation (e.g. '1', '25', '1.1').
        """
        token = raw_token.strip().rstrip(".:-—")
        if not token:
            return None

        # 1. Direct Arabic integer or dotted version (e.g. '1', '12', '2.1', '3.4.1')
        if re.match(r"^\d+(?:\.\d+)*$", token):
            return token

        # 2. Roman numeral (e.g. 'IV', 'xiv', 'IX')
        roman_val = cls.roman_to_int(token)
        if roman_val is not None:
            return str(roman_val)

        # 3. English word number (e.g. 'One', 'twenty-four')
        word_val = cls.words_to_int(token)
        if word_val is not None:
            return str(word_val)

        return None

    @classmethod
    def to_int(cls, raw_token: str) -> Optional[int]:
        """Extract an integer level from a token if convertible."""
        canonical = cls.parse_token(raw_token)
        if not canonical:
            return None

        if canonical.isdigit():
            return int(canonical)

        # If dotted (e.g. '2.1'), extract primary number
        parts = canonical.split(".")
        if parts and parts[0].isdigit():
            return int(parts[0])

        return None
