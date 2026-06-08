#!/usr/bin/env python3
"""
解析两个党史知识竞赛PDF，提取所有题目和答案，输出questions.json。
"""

import pdfplumber
import re
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PDF1 = os.path.join(BASE_DIR, "附件1-学生党史知识竞赛学习参考资料（2026）第1页-第181页.pdf")
PDF2 = os.path.join(BASE_DIR, "附件1-学生党史知识竞赛学习参考资料（2026）第182页-第303页.pdf")
OUTPUT = os.path.join(BASE_DIR, "questions.json")

HEADER_PATTERN = re.compile(r'哈尔滨工业大学党史知识竞赛')
PAGE_NUM_PATTERN = re.compile(r'^\d{1,3}\s*$')  # standalone page numbers


def clean_text(text):
    """Remove header lines and page numbers."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if HEADER_PATTERN.search(line):
            continue
        if PAGE_NUM_PATTERN.match(line):
            continue
        cleaned.append(line)
    return cleaned


def extract_all_text(pdf_path):
    """Extract and clean text from all pages of a PDF."""
    all_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines = clean_text(text)
                all_lines.extend(lines)
    return all_lines


def parse_questions(lines, start_num=1, qtype='single'):
    """
    Parse questions from cleaned text lines.

    Uses a state machine:
    - Looking for question number at line start
    - Accumulating question text across lines
    - Detecting option lines

    Returns list of question dicts.
    """
    questions = []
    current_q = None
    current_text_lines = []
    options = {}
    in_options = False

    # Pattern for question start: number followed by various separators
    # Handles: "1.", "1、", "1．", "1,", "1，" (Chinese comma), "1 " (space)
    q_start = re.compile(r'^(\d{1,4})[\.、．,\s，]\s*(.*)$')
    # Pattern for option: letter followed by various separators
    # Handles: "A、", "A.", "A．", "A " (space), "A," "A，"
    opt_pattern = re.compile(r'^([A-G])[、.．,\s，]\s*(.*)$')
    # Pattern to split inline options: find option letter boundaries
    # Matches at position before [A-G] followed by separator, OR [A-G] directly followed
    # by Chinese char or digit (no-separator format like "A.丁肇中B李政道")
    inline_split = re.compile(
        r'\s*(?=[A-G](?:[、.．,\s，]|(?=[一-鿿\d“‘（\(])))'
    )

    def parse_inline_options(line):
        """Parse inline options like 'A、xxx B、xxx C、xxx' into dict."""
        parts = inline_split.split(line)
        options = {}
        for part in parts:
            part = part.strip()
            if not part:
                continue
            m = re.match(r'([A-G])[、.．,\s，]?\s*(.*)', part)
            if m:
                key = m.group(1)
                val = m.group(2).strip()
                if val:
                    options[key] = val
        return options if len(options) >= 2 else {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if this line starts a new question
        qm = q_start.match(line)
        if qm:
            num = int(qm.group(1))
            rest = qm.group(2).strip()

            # Filter out false positives: years (1938, 1949, etc.) and other
            # large numbers that aren't real question IDs (max real ID is 765)
            if num > 900:
                # This is likely a year or other number, not a question ID
                if in_options:
                    # Append to last option as continuation
                    last_key = list(options.keys())[-1]
                    options[last_key] += line
                else:
                    current_text_lines.append(line)
                continue

            # Save previous question (only if it has question text AND options)
            if current_q is not None and options and current_text_lines:
                current_q['question'] = '\n'.join(current_text_lines).strip()
                current_q['options'] = options
                questions.append(current_q)

            # Start new question
            current_q = {'id': num, 'type': qtype}
            current_text_lines = [rest] if rest else []
            options = {}
            in_options = False
            continue

        # Check if line contains inline options (e.g., "A、xxx B、xxx C、xxx")
        # Must check BEFORE single-option-line check to avoid greedy match
        inline_opts = parse_inline_options(line)
        if len(inline_opts) >= 2:
            # Extract question part (before first option)
            first_opt_pos = len(line)  # will find earliest option
            for key in inline_opts:
                idx = line.find(key + '、')
                if idx == -1:
                    idx = line.find(key + '.')
                if idx == -1:
                    idx = line.find(key + '，')
                if idx == -1:
                    idx = line.find(key + '．')
                if idx == -1:
                    idx = line.find(key + ' ')
                if idx == -1:
                    # No separator: letter followed by Chinese char
                    m = re.search(rf'{key}(?=[一-鿿\d])', line)
                    if m:
                        idx = m.start()
                if idx != -1:
                    first_opt_pos = min(first_opt_pos, idx)

            question_part = line[:first_opt_pos].strip()
            if question_part and not in_options:
                current_text_lines.append(question_part)

            options.update(inline_opts)
            in_options = True
            continue

        # Check if this line is a single option line
        om = opt_pattern.match(line)
        if om:
            in_options = True
            key = om.group(1)
            val = om.group(2).strip()
            options[key] = val
            continue

        # Otherwise, this is continuation text
        if in_options:
            # Might be continuation of an option on a new line
            if options and not q_start.match(line):
                # Append to last option, unless it starts a new option
                if not opt_pattern.match(line):
                    last_key = list(options.keys())[-1]
                    options[last_key] += line
        else:
            # Before options section: accumulate question text
            current_text_lines.append(line)

    # Don't forget the last question
    if current_q is not None and options:
        current_q['question'] = '\n'.join(current_text_lines).strip()
        current_q['options'] = options
        questions.append(current_q)

    return questions


def parse_single_choice_answers(lines):
    """Parse single choice answers from answer key pages."""
    answers = {}
    # Match patterns like "1.B 2.C 3.B" or "705.B 706.C"
    ans_pattern = re.compile(r'(\d+)\.([A-E])')

    for line in lines:
        for m in ans_pattern.finditer(line):
            num = int(m.group(1))
            ans = m.group(2)
            answers[num] = ans

    return answers


def parse_multiple_choice_answers(lines):
    """Parse multiple choice answers from answer key pages.
    Only matches 2+ letter answers to avoid picking up single-choice answers.
    """
    answers = {}
    # Match patterns like "1.BC 2.AB 3.ACD" (at least 2 letters)
    ans_pattern = re.compile(r'(?<!\d)(\d+)\.([A-F]{2,})')

    for line in lines:
        for m in ans_pattern.finditer(line):
            num = int(m.group(1))
            ans = m.group(2)
            # Sort the answer letters, skip if it looks like a single-choice answer
            if len(ans) >= 2:
                answers[num] = ''.join(sorted(ans))

    return answers


def clean_question_text(text):
    """Clean up question text."""
    # Remove excessive whitespace
    text = re.sub(r'\s+', '', text)
    # Fix common OCR/style issues
    text = text.replace('（', '(').replace('）', ')')
    text = text.replace('∶', ':').replace('∶', ':')
    return text.strip()


def clean_option_text(text):
    """Clean up option text."""
    text = text.strip()
    # Remove extra spaces within Chinese text
    text = re.sub(r'\s+', '', text)
    return text


def post_process_questions(questions):
    """Clean up question and option text."""
    for q in questions:
        q['question'] = clean_question_text(q['question'])
        cleaned_options = {}
        for k, v in q['options'].items():
            cleaned_options[k] = clean_option_text(v)
        q['options'] = cleaned_options
    return questions


def main():
    print("=" * 60)
    print("党史知识竞赛题库提取工具")
    print("=" * 60)

    # ── Extract questions from PDF1 (single choice 1-719) ──
    print("\n[1/4] 解析第一个PDF（单选题1-719）...")
    lines1 = extract_all_text(PDF1)
    print(f"  提取到 {len(lines1)} 行文本")

    single1 = parse_questions(lines1, start_num=1, qtype='single')
    print(f"  解析出 {len(single1)} 道单选题")

    # ── Extract questions from PDF2 (single choice 720-765 + multiple choice) ──
    print("\n[2/4] 解析第二个PDF（单选题720-765 + 多选题）...")
    lines2 = extract_all_text(PDF2)
    print(f"  提取到 {len(lines2)} 行文本")

    # Split PDF2: single choice section (questions 720-765) + multiple choice section
    # Find where single choice ends and multiple choice begins
    single2 = []
    multi_all = []

    # Look for the transition point - "二、多项选择" or similar
    in_multi = False
    single_lines = []
    multi_lines = []

    for line in lines2:
        if re.search(r'二[、.]\s*多[项选]', line) or re.search(r'多[项选]择', line):
            in_multi = True
            continue
        if in_multi:
            multi_lines.append(line)
        else:
            single_lines.append(line)

    if single_lines:
        single2 = parse_questions(single_lines, start_num=720, qtype='single')
        # Filter to only get questions numbered 720+
        single2 = [q for q in single2 if q['id'] >= 720]
    print(f"  解析出 {len(single2)} 道单选题（720-765）")

    if multi_lines:
        multi_all = parse_questions(multi_lines, start_num=1, qtype='multiple')
    print(f"  解析出 {len(multi_all)} 道多选题")

    # ── Parse answers ──
    print("\n[3/4] 解析答案...")

    # IMPORTANT: Separate single and multi answer pages!
    # Single choice answers: PDF2 pages 116-120 (0-indexed: 115-119)
    # Multiple choice answers: PDF2 pages 121-122 (0-indexed: 120-121)
    # Mixing them causes multi answers like "26.ABD" to be parsed as "26.A",
    # overwriting the correct single choice answer "26.C"
    with pdfplumber.open(PDF2) as pdf:
        single_answer_lines = []
        for i in range(115, min(120, len(pdf.pages))):
            text = pdf.pages[i].extract_text()
            if text:
                single_answer_lines.extend(clean_text(text))

        multi_answer_lines = []
        for i in range(120, min(122, len(pdf.pages))):
            text = pdf.pages[i].extract_text()
            if text:
                multi_answer_lines.extend(clean_text(text))

    single_answers = parse_single_choice_answers(single_answer_lines)
    multi_answers = parse_multiple_choice_answers(multi_answer_lines)

    print(f"  解析出 {len(single_answers)} 个单选题答案")
    print(f"  解析出 {len(multi_answers)} 个多选题答案")

    # ── Merge and validate ──
    print("\n[4/4] 合并题库并验证...")

    # Combine single choice questions
    all_single = single1 + single2

    # Assign answers to single choice
    single_matched = 0
    single_missing = []
    for q in all_single:
        if q['id'] in single_answers:
            q['answer'] = single_answers[q['id']]
            single_matched += 1
        else:
            single_missing.append(q['id'])

    # Assign answers to multiple choice
    multi_matched = 0
    multi_missing = []
    for q in multi_all:
        if q['id'] in multi_answers:
            q['answer'] = multi_answers[q['id']]
            multi_matched += 1
        else:
            multi_missing.append(q['id'])

    # Keep only questions with answers
    single_final = [q for q in all_single if 'answer' in q]
    multi_final = [q for q in multi_all if 'answer' in q]

    # Post-process
    single_final = post_process_questions(single_final)
    multi_final = post_process_questions(multi_final)

    # ── Output ──
    output = {
        "singleChoice": single_final,
        "multipleChoice": multi_final
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(OUTPUT)
    print(f"\n{'='*60}")
    print(f"✅ 题库提取完成！")
    print(f"  单选题: {len(single_final)} 道（含答案）")
    print(f"  多选题: {len(multi_final)} 道（含答案）")
    print(f"  总计:   {len(single_final) + len(multi_final)} 道")
    print(f"  文件:   {OUTPUT}")
    print(f"  大小:   {file_size / 1024:.1f} KB")
    print(f"{'='*60}")

    if single_missing:
        print(f"\n⚠️  单选题缺少答案: {len(single_missing)} 道 → {single_missing[:20]}...")
    if multi_missing:
        print(f"\n⚠️  多选题缺少答案: {len(multi_missing)} 道 → {multi_missing[:20]}...")

    # Print a few samples
    print("\n📋 单选题样例:")
    for q in single_final[:3]:
        print(f"  [{q['id']}] {q['question'][:60]}... → 答案: {q['answer']}")

    print("\n📋 多选题样例:")
    for q in multi_final[:3]:
        print(f"  [{q['id']}] {q['question'][:60]}... → 答案: {q['answer']}")


if __name__ == '__main__':
    main()
