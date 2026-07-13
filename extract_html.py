import re

with open(r'C:\Users\chris\.local\share\opencode\tool-output\tool_e8ba1144a001Tv50pUDcHzSx6q', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all occurrences of 'text":' followed by content
idx = 0
count = 0
while count < 200:
    idx = content.find('"text":', idx)
    if idx == -1:
        break
    start = idx + 8  # skip '"text":'
    # Check if next char is a quote
    if start < len(content) and content[start] == '"':
        # Find the closing unescaped quote
        end = start + 1
        while end < len(content):
            c = content[end]
            if c == '\\' and end + 1 < len(content):
                end += 2
                continue
            if c == '"':
                break
            end += 1
        text_val = content[start+1:end]
        if len(text_val) > 30:
            # Unescape
            text_val = text_val.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
            print(f'--- Text {count} (len={len(text_val)}) ---')
            print(text_val[:2000])
            print()
            count += 1
        idx = end
    else:
        idx = start

print(f"\nTotal text entries processed: {count}")
