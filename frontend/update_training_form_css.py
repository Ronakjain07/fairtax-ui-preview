import re

filepath = 'e:/fairtax/frontend/css/training-v2.css'

with open(filepath, 'r', encoding='utf-8') as f:
    css = f.read()

# Add the form reset block at the end of the file
form_reset = """

/* ── Nuke generic form styling from style.css ── */
body.tr-page form {
  background: transparent !important;
  backdrop-filter: none !important;
  box-shadow: none !important;
  border: none !important;
  border-radius: 0 !important;
  padding: 0 !important;
  margin: 0 !important;
  animation: none !important;
}
body.tr-page form::before,
body.tr-page form::after {
  display: none !important;
}

"""

if 'Nuke generic form styling' not in css:
    css += form_reset

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(css)

print("Added form reset to training-v2.css")
