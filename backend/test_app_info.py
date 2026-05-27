import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app import app, save_phase

print(f"\n=== Flask App Info ===")
print(f"App object: {app}")
print(f"App modules in __dict__: {len(app.__dict__)}")

# Check if save_phase is registered
found = False
for rule in app.url_map.iter_rules():
    if 'save_phase' in rule.rule or 'save-phase' in rule.rule:
        print(f"Found route: {rule.rule} -> {rule.endpoint}")
        found = True

if not found:
    print("WARNING: save_phase route not found!")

# Now run the app
print("\n=== Starting Flask ===\n")
app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
