import sys

with open('scripts/build_dong_history.py', 'r') as f:
    code = f.read()

old_logic = """        if c == 0:
            data["grade"] = 1
        elif c == 1:
            data["grade"] = 2
        elif c == 2:
            data["grade"] = 3
        elif c == 3:
            data["grade"] = 4
        else:
            data["grade"] = 5"""

new_logic = """        if c <= 2:
            data["grade"] = 1
        elif c <= 5:
            data["grade"] = 2
        elif c <= 8:
            data["grade"] = 3
        elif c <= 12:
            data["grade"] = 4
        else:
            data["grade"] = 5"""

code = code.replace(old_logic, new_logic)

with open('scripts/build_dong_history.py', 'w') as f:
    f.write(code)

print("Grade logic patched.")
