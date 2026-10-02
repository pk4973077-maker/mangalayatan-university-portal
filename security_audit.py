import re

APP_FILE = "app.py"

with open(APP_FILE, "r", encoding="utf-8") as file:
    code = file.read()

# @app.route se route blocks alag karo
blocks = re.split(r"(?=@app\.route)", code)

print()
print("=" * 60)
print("        FLASK ROUTE SECURITY AUDIT")
print("=" * 60)
print()

protected_patterns = [
    "admin_required()",
    'session.get("admin_id")',
    "session.get('admin_id')",
    'session.get("faculty_id")',
    "session.get('faculty_id')",
    'session.get("student_enrollment")',
    "session.get('student_enrollment')",
    'session.get("student_id")',
    "session.get('student_id')",
]

for block in blocks:

    route_match = re.search(
        r'@app\.route\(\s*["\']([^"\']+)',
        block
    )

    if not route_match:
        continue

    route = route_match.group(1)

    # Route ka function name
    function_match = re.search(
        r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
        block
    )

    if function_match:
        function_name = function_match.group(1)
    else:
        function_name = "unknown"

    found = []

    for pattern in protected_patterns:
        if pattern in block:
            found.append(pattern)

    # Public routes
    public_words = [
        "login",
        "logout",
        "static",
        "favicon"
    ]

    is_public = any(
        word in route.lower()
        for word in public_words
    )

    print("-" * 60)
    print("ROUTE :", route)
    print("FUNCTION :", function_name)

    if found:
        print("STATUS : 🟢 PROTECTION CHECK FOUND")

        for item in found:
            print("         ", item)

    elif is_public:
        print("STATUS : 🟡 LIKELY PUBLIC ROUTE")

    else:
        print("STATUS : 🔴 NO OBVIOUS SESSION CHECK")

print()
print("=" * 60)
print("              AUDIT COMPLETE")
print("=" * 60)
print()