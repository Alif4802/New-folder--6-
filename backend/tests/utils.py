import io
import pymupdf


def create_synthetic_english_today_pdf() -> bytes:
    """
    Generate a 3-page synthetic NCTB 'English for Today' textbook PDF (Class 9, 2024).
    Contains Title & Front matter, Table of Contents, and Unit 1 Lesson 1.
    """
    doc = pymupdf.open()

    # Page 1: Title & Front Matter
    p1 = doc.new_page(width=595, height=842)  # A4 size
    p1.insert_text((72, 100), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=12)
    p1.insert_text((72, 150), "English for Today", fontsize=24)
    p1.insert_text((72, 190), "Class 9", fontsize=16)
    p1.insert_text((72, 230), "Academic Year 2024", fontsize=12)
    p1.insert_text((72, 270), "Prescribed by the National Curriculum and Textbook Board as a textbook.", fontsize=10)

    # Page 2: Table of Contents
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 100), "Table of Contents", fontsize=18)
    p2.insert_text((72, 140), "Unit 1: Father of the Nation ................................. Page 3", fontsize=11)
    p2.insert_text((72, 170), "Unit 2: Pastimes ............................................ Page 15", fontsize=11)

    # Page 3: Unit 1, Lesson 1
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 80), "Unit 1 : Father of the Nation", fontsize=20)
    p3.insert_text((72, 120), "Lesson 1 : Bangabandhu's Family in 1971", fontsize=15)
    
    # Instruction
    p3.insert_text((72, 160), "Look at the picture and discuss the questions in pairs.", fontsize=11)
    
    # Dialogue
    p3.insert_text((72, 200), "Ruma: Have you heard about the historic events of 1971?", fontsize=11)
    p3.insert_text((72, 220), "Sujon: Yes, it is the most memorable year in our history.", fontsize=11)
    
    # Reading Passage
    p3.insert_text((72, 260), "Read the following passage carefully.", fontsize=11)
    p3.insert_text(
        (72, 285),
        "It was the night of 25 March 1971. There was a quiet atmosphere at Bangabandhu's home.\n"
        "Bangabandhu Sheikh Mujibur Rahman anticipated the attack on the innocent people of Dhaka.\n"
        "He sent his family members to a safer place before his arrest by the Pakistani army.",
        fontsize=11,
    )
    
    # Vocabulary
    p3.insert_text((72, 360), "Vocabulary", fontsize=13)
    p3.insert_text((72, 385), "Anticipate - to expect beforehand", fontsize=10)
    p3.insert_text((72, 405), "Innocent - not guilty of a crime", fontsize=10)
    
    # Exercise
    p3.insert_text((72, 440), "Questions and Exercises", fontsize=13)
    p3.insert_text((72, 465), "1. What happened on the night of 25 March 1971?", fontsize=10)
    p3.insert_text((72, 485), "2. Where did Bangabandhu send his family?", fontsize=10)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_english_grammar_pdf() -> bytes:
    """
    Generate a 2-page synthetic NCTB 'English Grammar and Composition' textbook PDF (Class 9, 2024).
    Contains Title Page and Unit 1 Lesson 1 with Grammar Rules and Exercises.
    """
    doc = pymupdf.open()

    # Page 1: Title Page
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=12)
    p1.insert_text((72, 140), "English Grammar and Composition", fontsize=22)
    p1.insert_text((72, 180), "Class 9", fontsize=16)
    p1.insert_text((72, 210), "Academic Year 2024", fontsize=12)

    # Page 2: Unit 1, Lesson 1 with Grammar Rules and Exercises
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 80), "Unit 1 : Sentence Structure", fontsize=20)
    p2.insert_text((72, 120), "Lesson 1 : Types of Sentences", fontsize=15)
    p2.insert_text((72, 160), "Grammar Rule: An assertive sentence makes a statement.", fontsize=11)
    p2.insert_text(
        (72, 190),
        "A sentence is a group of words that expresses a complete thought.\n"
        "Sentences can be assertive, interrogative, imperative, optative, or exclamatory.",
        fontsize=11,
    )
    p2.insert_text((72, 260), "Exercise: Identify the sentence types below.", fontsize=12)
    p2.insert_text((72, 285), "1. The sun rises in the east.", fontsize=10)
    p2.insert_text((72, 305), "2. What is your favorite book?", fontsize=10)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_synthetic_mathematics_pdf() -> bytes:
    """
    Generate a 2-page synthetic NCTB 'Mathematics' textbook PDF (Class 9, 2024).
    Contains Title Page and Chapter 1 with Definitions, Theorems, Worked Examples, and Exercises.
    """
    doc = pymupdf.open()

    # Page 1: Title Page
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=12)
    p1.insert_text((72, 140), "Mathematics", fontsize=24)
    p1.insert_text((72, 180), "Class 9", fontsize=16)
    p1.insert_text((72, 210), "Academic Year 2024", fontsize=12)

    # Page 2: Chapter 1 - Real Numbers
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 80), "Chapter 1 : Real Numbers", fontsize=20)
    p2.insert_text((72, 120), "1.1 Introduction to Real Numbers", fontsize=15)
    
    # Definition
    p2.insert_text((72, 160), "Definition: A rational number is a number that can be expressed as p / q.", fontsize=11)
    
    # Theorem & Proof
    p2.insert_text((72, 200), "Theorem 1.1: The square root of 2 is an irrational number.", fontsize=12)
    p2.insert_text((72, 230), "Proof: Suppose root 2 is rational. Then root 2 = a / b in lowest terms.", fontsize=11)
    
    # Worked Example
    p2.insert_text((72, 280), "Worked Example 1: Simplify the expression (2 + root 3) * (2 - root 3).", fontsize=11)
    p2.insert_text((72, 305), "Solution: (2)^2 - (root 3)^2 = 4 - 3 = 1.", fontsize=11)
    
    # Exercise
    p2.insert_text((72, 350), "Exercise 1.1", fontsize=14)
    p2.insert_text((72, 380), "1. Prove that root 3 is an irrational number.", fontsize=10)
    p2.insert_text((72, 400), "2. Express 0.333... as a rational fraction in simplest form.", fontsize=10)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
