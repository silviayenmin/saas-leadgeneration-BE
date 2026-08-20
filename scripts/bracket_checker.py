with open("d:\\Project\\Silvia\\saas-product\\saas-leadgeneration-adminpanel\\src\\pages\\AdminPanel.scss", "r") as f:
    lines = f.readlines()

depth = 0
for idx, line in enumerate(lines):
    # count brackets
    opens = line.count('{')
    closes = line.count('}')
    if opens > 0 or closes > 0:
        old_depth = depth
        depth += opens - closes
        print(f"Line {idx+1:3d}: depth {old_depth} -> {depth} | {line.strip()}")
