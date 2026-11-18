with open('app.py', encoding='utf-8') as f:
    text = f.read()

import re
matches = re.finditer(r'@app\.route\([^)]+\)\s*(?:@[^\n]+\s*)*def\s+([a-zA-Z0-9_]+)', text)
for m in matches:
    route_header = m.group(0)
    if any(k in route_header.lower() for k in ['attend', 'face', 'recogni', 'verify', 'camera', 'esp32', 'scan']):
        print(route_header)
        print('-'*30)

