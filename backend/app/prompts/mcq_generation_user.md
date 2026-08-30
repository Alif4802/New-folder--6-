### ASSESSMENT GENERATION REQUEST
- Textbook: {{ textbook_title }}
- Grade: {{ grade_name }}
- Subject: {{ subject_name }}
- Scope: {{ scope_description }}
- Requested MCQ Count: {{ requested_count }}

### INSTRUCTIONS
Generate exactly {{ requested_count }} high-quality, distinct MCQs based strictly on the source chunks below.
Ensure balanced coverage across the provided source chunks where the requested question count permits.
Vary question angles, stems, and option positions.

{% if exclusion_ledger_text %}
<EXCLUSION_LEDGER>
Do NOT duplicate or repeat the following already-generated questions or concepts:
{{ exclusion_ledger_text }}
</EXCLUSION_LEDGER>
{% endif %}

<TEXTBOOK_SOURCE_DATA>
{{ source_chunks_text }}
</TEXTBOOK_SOURCE_DATA>
