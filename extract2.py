import re

with open(r'C:\Users\chris\.local\share\opencode\tool-output\tool_e8ba1144a001Tv50pUDcHzSx6q', 'r', encoding='utf-8') as f:
    content = f.read()

matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', content, re.DOTALL))
s3 = matches[3].group(1)

# Try parsing the parts structure
# Find all message part entries with type
# Pattern: msg_XXXX:$R[N]=[$R[...]={type:"...",
msg_pattern = r'(msg_[a-zA-Z0-9]+):\$R\[\d+\]=\['
msg_matches = list(re.finditer(msg_pattern, s3))

print(f'Found {len(msg_matches)} messages')
for i, m in enumerate(msg_matches):
    print(f'\n{"="*80}')
    msg_id = m.group(1)
    print(f'MESSAGE {i}: {msg_id}')
    
    # Get a chunk of content after this message
    start = m.start()
    end = min(start + 15000, len(s3))  # Get more context
    chunk = s3[start:end]
    
    # Extract text parts
    text_pattern = r'\{type:"text",text:"((?:[^"\\]|\\.)*)"'
    text_matches = re.findall(text_pattern, chunk)
    for j, tm in enumerate(text_matches):
        t = tm.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
        if len(t) > 20:
            print(f'  TEXT {j}: {t[:500]}')
    
    # Extract reasoning parts
    reason_pattern = r'\{type:"reasoning",text:"((?:[^"\\]|\\.)*)"'
    reason_matches = re.findall(reason_pattern, chunk)
    for j, rm in enumerate(reason_matches):
        r = rm.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
        if len(r) > 20:
            print(f'  REASON {j}: {r[:300]}...')
    
    # Extract tool parts
    tool_pattern = r'\{type:"tool",callID:"([^"]+)",tool:"([^"]+)",'
    tool_matches = re.findall(tool_pattern, chunk)
    for j, tm in enumerate(tool_matches):
        print(f'  TOOL {j}: {tm[1]} (callID: {tm[0][:30]}...)')
    
    if i > 30:
        break

# Also extract from the parts structure
print('\n\n=== PARTS STRUCTURE ===')
parts_pattern = r'msg_([a-zA-Z0-9]+):\$R\[\d+\]=\['
parts_sections = list(re.finditer(parts_pattern, s3))
print(f'Total message parts: {len(parts_sections)}')
