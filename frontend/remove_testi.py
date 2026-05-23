import re

with open('e:/fairtax/frontend/landing.html', 'r', encoding='utf-8') as f:
    content = f.read()

# The section starts with <!-- ═══════════════════ TESTIMONIALS ═══════════════════ -->
# and ends with </section> before <!-- ═══════════════════ WE CARE ═══════════════════ -->

pattern = re.compile(
    r'\s*<!-- ═══════════════════ TESTIMONIALS ═══════════════════ -->\s*<section class="lv2-testimonials">.*?</section>',
    re.DOTALL
)

new_content = pattern.sub('', content)

if content != new_content:
    with open('e:/fairtax/frontend/landing.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Testimonials section removed successfully.")
else:
    print("Could not find the testimonials section to remove.")
