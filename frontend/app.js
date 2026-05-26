const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:5000/api'
  : 'https://fairtax-backend.onrender.com/api';

let currentStep = 1;
const TOTAL = 7;

// ❗ REPLACED phone with submission_id
let submissionId = localStorage.getItem("submission_id") || "";

// Store refund amounts from backend calculation
let refundAmounts = { A: 0, B: 0, C: 0 };
// 🔥 RESET if backend restarted
if (!localStorage.getItem("session_active")) {
  localStorage.removeItem("submission_id");
  localStorage.setItem("session_active", "1");
}

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

// ─── PREMIUM ANIMATION & INTERACTION FUNCTIONS (Global Scope) ──────────
function showReferralTeaser() {
  const teaser = document.getElementById("referralTeaser");
  if (teaser) {
    teaser.style.display = "block";
    setTimeout(() => {
      teaser.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  }
}

function scrollToForm() {
  const formCard = document.querySelector("form");
  if (formCard) {
    formCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function celebrateUnlock(message, emoji) {
  const celebration = document.createElement("div");
  celebration.className = "milestone-celebration";
  celebration.innerHTML = `
    <span class="celebration-emoji">${emoji}</span>
    <h3 style="font-size:20px;margin:12px 0;font-weight:900">${message}</h3>
  `;
  document.body.appendChild(celebration);

  setTimeout(() => {
    celebration.style.opacity = "0";
    celebration.style.transform =
      "translate(-50%, -50%) scale(0.5) rotate(-10deg)";
    celebration.style.transition = "all 0.4s ease";
    setTimeout(() => celebration.remove(), 400);
  }, 2000);
}

function checkReferralsComplete() {
  let count = 0;
  for (let i = 1; i <= 5; i++) {
    const nameField = $(`[name="ref_name_${i}"]`);
    const phoneField = $(`[name="ref_phone_${i}"]`);
    if (nameField && phoneField && nameField.value && phoneField.value) {
      count++;
    }
  }
  return count;
}

function updateReferralTeaser() {
  const refs = checkReferralsComplete();
  const remaining = Math.max(0, 5 - refs);
  const status =
    refs === 5
      ? "✅ Unlocked"
      : remaining === 0
        ? "✅ Unlocked"
        : `${remaining} more`;

  const referralsNeedEl = document.getElementById("referralsNeeded");
  const statusEl = document.getElementById("filingStatus");

  if (referralsNeedEl) referralsNeedEl.textContent = remaining;
  if (statusEl) statusEl.textContent = status;

  // Show celebration if just unlocked
  if (remaining === 0 && refs === 5) {
    celebrateUnlock("🎉 Free Filing Unlocked!", "🎊");
  }

  // Update milestone tracker
  updateMilestoneTracker(refs);
}

function updateMilestoneTracker(refs) {
  for (let i = 1; i <= 5; i++) {
    const circle = $(`#milestone-circle-${i}`);
    const step = $(`#milestone-${i}`);
    if (circle && step) {
      if (i <= refs) {
        circle.classList.remove("locked");
        circle.classList.add("unlocked");
        step.classList.add("unlocked");
      } else {
        circle.classList.add("locked");
        circle.classList.remove("unlocked");
        step.classList.remove("unlocked");
      }
    }
  }
}

function initEnhancedMilestoneTracker() {
  const tracker = document.getElementById("enhancedMilestoneTracker");
  const rewards = document.getElementById("rewardCardsContainer");
  const cta = document.getElementById("conversionCtaSection");

  if (filingType === "free") {
    if (tracker) tracker.style.display = "block";
    if (rewards) rewards.style.display = "block";
    if (cta) cta.style.display = "block";
    updateReferralTeaser();
  }
}

function initScrollAnimations() {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.1 },
  );

  $$(
    ".scroll-fade-in, .scroll-slide-left, .scroll-slide-right, .premium-reward-card, .conversion-cta-section",
  ).forEach((el) => {
    observer.observe(el);
  });
}

function showStep(n) {
  $$(".step").forEach((s) => s.classList.remove("active"));
  $(`.step[data-step="${n}"]`).classList.add("active");
  if (n <= TOTAL) {
    $("#bar").style.width = (n / TOTAL) * 100 + "%";
    $("#stepLabel").textContent = `Step ${n} of ${TOTAL}`;
  } else {
    $("#bar").style.width = "100%";
    $("#stepLabel").textContent = `Submitted`;
  }

  // Navigation visibility rules:
  // - Prev: visible on steps 2..(TOTAL-1) (hide on thank-you step)
  // - Next: visible on steps before the Confirm step (1..TOTAL-2)
  // - Submit: visible on the Confirm step only (TOTAL-1)
  // - On thank-you (TOTAL), hide prev/next/submit
  const isThankYou = n === TOTAL;
  $("#prev").style.display = n > 1 && n < TOTAL ? "block" : "none";
  $("#next").style.display = n >= 1 && n < TOTAL - 1 ? "block" : "none";
  $("#submit").style.display = n === TOTAL - 1 ? "block" : "none";

  if (isThankYou) {
    $("#prev").style.display = "none";
    $("#next").style.display = "none";
    $("#submit").style.display = "none";
  }

  // Update offer/reveal button visibility whenever the visible step changes
  try {
    updateOfferButtons();
  } catch (e) {
    /* ignore */
  }
}

function collectStep(n) {
  const obj = {};
  $(`.step[data-step="${n}"]`)
    .querySelectorAll("input,select,textarea")
    .forEach((el) => {
      if (!el.name) return;

      if (el.type === "checkbox") obj[el.name] = el.checked ? "1" : "";
      else if (el.value !== undefined) obj[el.name] = el.value;
    });

  return obj;
}

function validateStep(n) {
  const inputs = $(`.step[data-step="${n}"]`).querySelectorAll(
    "input[required], select[required]",
  );

  for (const i of inputs) {
    if (i.offsetParent === null) continue;
    if (!i.checkValidity()) {
      i.reportValidity();
      return false;
    }
  }
  // If user picked Free Tax, require referral step complete on step 1
  if (n === 1 && filingType === "free") {
    if (!referralCode && !checkReferralsComplete()) {
      alert("Please complete 5 referrals to continue with Free Tax.");
      return false;
    }
  }
  return true;
}

// ── SAVE PHASE (collect current step data and persist to backend) ──────
async function savePhase(extraData) {
  try {
    // Collect all form data from current step (unless extraData was passed)
    let stepData = extraData || collectStep(currentStep);

    // Ensure filing_type/filing_category is set for regular filings
    if (filingType === "regular" && !stepData.filing_category) {
      stepData.filing_category = "regular";
    } else if (filingType === "free" && !stepData.filing_category) {
      stepData.filing_category = "free";
    }

    // If we have a submission ID, include it
    if (submissionId) {
      stepData.submission_id = submissionId;
    }

    // Send to backend
    const r = await fetch(`${API}/save-phase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(stepData),
    });

    const j = await r.json();

    if (!j.success) {
      console.error("[SAVE_PHASE] Error:", j.error);
      throw new Error(j.error || "Failed to save");
    }

    // Store the submission ID for future steps
    if (j.submission_id) {
      submissionId = j.submission_id;
      localStorage.setItem("submission_id", submissionId);
      console.log("[SAVE_PHASE] ✅ Saved. submission_id =", submissionId);
    }

    // Store referral code if backend returned one
    if (j.referral_code) {
      referralCode = j.referral_code;
      localStorage.setItem("referral_code", referralCode);
      const rcEl = document.querySelector('[name="referral_code"]');
      if (rcEl) rcEl.value = referralCode;
    }

    return j;
  } catch (e) {
    console.error("[SAVE_PHASE] Exception:", e);
    alert("Error saving your progress: " + e.message);
    throw e; // Re-throw so caller knows it failed
  }
}

// Filing type (Regular / Free) and referral flow
// index.html is for regular tax filing only
let filingType = "regular"; // Pre-set to regular filing on index.html
let referralCode = localStorage.getItem("referral_code") || "";
let cameraStream = null;
let cameraTargetInput = null;
async function uploadDocs(inputId, docType) {
  const input = $(`#${inputId}`);
  if (!input || !input.files.length) return;

  const fd = new FormData();

  [...input.files].forEach((f) => fd.append("file", f));
  fd.append("doc_type", docType);

  const status = $("#extractStatus");
  const loader = document.getElementById("extractionLoader");

  if (loader) {
    loader.style.display = "block";
    loader.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  if (status) {
    status.className = "status loading";
    status.textContent = "🔍 AI reading your documents...";
  }

  try {
    // Use /api/itr/extract for ITR-specific extraction
    const r = await fetch(`${API}/itr/extract`, { method: "POST", body: fd });
    const j = await r.json();

    if (j.success && j.data) {
      // Auto-fill extracted fields into Step 4 review form
      const extracted = j.data;

      // Personal info — only auto-fill when the corresponding input is empty
      if (extracted.personal) {
        const p = extracted.personal || {};
        // Fill pan/phone/email only if field is empty
        ["pan", "phone", "email"].forEach((k) => {
          const el = document.querySelector(`[name="${k}"]`);
          try {
            if (!el) return;
            const cur = (el.value || "").toString().trim();
            if ((!cur || cur.length === 0) && p[k]) el.value = p[k];
          } catch (e) {
            /* ignore */
          }
        });

        // Fill name only when user hasn't already entered their name
        try {
          const nameEl = document.querySelector('[name="name"]');
          const curName =
            (nameEl && (nameEl.value || "").toString().trim()) || "";
          if (nameEl && !curName && p.name) nameEl.value = p.name;
        } catch (e) {
          /* ignore */
        }
      }

      // Income info — fill all salary fields
      // Use inc[k] first (nested income object), fall back to extracted[k] (top-level)
      // This handles cases where AI returns 0 in the nested mapping but correct value at top level.
      if (extracted.income) {
        const inc = extracted.income;
        [
          "gross_salary", "basic_salary", "hra_received", "tds_paid",
          "pf_employee", "pf_employer", "professional_tax",
          "lta", "special_allowance", "car_lease_allowance",
          "uniform_allowance", "gratuity", "leave_encashment"
        ].forEach((k) => {
          const el = document.querySelector(`[name="${k}"]`);
          if (!el) return;
          // Prefer nested inc[k], fall back to top-level extracted[k]
          const val = inc[k] || extracted[k];
          if (val) el.value = val;
          console.log(`[FILL] ${k}: inc=${inc[k]}, top=${extracted[k]}, used=${val}`);
        });
      }

      // Deductions
      if (extracted.deductions) {
        const ded = extracted.deductions;
        ["home_loan_interest", "nps_self", "home_loan_principal", "nps_employer",
         "school_fees", "nps_pran"].forEach((k) => {
          const el = document.querySelector(`[name="${k}"]`);
          if (!el) return;
          const val = ded[k] || extracted[k];
          if (val) el.value = val;
        });
      }

      // ✅ AUTO-SAVE extracted data to Google Sheets immediately
      try {
        const inc = extracted.income || {};
        const ded = extracted.deductions || {};
        // Use nested inc/ded fields with top-level extracted fallback (same logic as form filling)
        const flatData = {
          gross_salary: inc.gross_salary || extracted.gross_salary || 0,
          basic_salary: inc.basic_salary || extracted.basic_salary || 0,
          hra_received: inc.hra_received || extracted.hra_received || 0,
          tds_paid: inc.tds_paid || extracted.tds_paid || 0,
          pf_employee: inc.pf_employee || extracted.pf_employee || 0,
          pf_employer: inc.pf_employer || extracted.pf_employer || 0,
          professional_tax: inc.professional_tax || extracted.professional_tax || 0,
          lta: inc.lta || extracted.lta || 0,
          special_allowance: inc.special_allowance || extracted.special_allowance || 0,
          home_loan_interest: ded.home_loan_interest || extracted.home_loan_interest || 0,
          nps_self: ded.nps_self || extracted.nps_self || 0,
          pan: extracted.personal?.pan || extracted.pan || "",
        };
        await savePhase(flatData);
        console.log(
          "[EXTRACTION] ✅ Extracted data auto-saved to Google Sheets",
        );
      } catch (e) {
        console.warn(
          "[EXTRACTION] ⚠️ Auto-save failed (will save when user clicks Next):",
          e,
        );
      }

      if (status) {
        status.className = "status success";
        _lastExtraction[inputId] = { data: j.data, docType };
        status.innerHTML = `✅ Extracted & Saved! Review on next step. ${_dvVerifyBtn(inputId)}`;
      }
    } else if (status) {
      status.className = "status error";
      status.textContent = "⚠️ Could not extract — fill manually.";
    }
  } catch (e) {
    if (status) {
      status.className = "status error";
      status.textContent = "❌ " + e.message;
    }
  } finally {
    if (loader) {
      loader.style.display = "none";
    }
  }
}

// (filingType variables declared above)

function setFilingType(type) {
  filingType = type;
  const hidden = document.querySelector("[name='filing_type']");
  if (hidden) hidden.value = type;
  if (type === "free") {
    document.getElementById("freeReferralSection").style.display = "block";
    document.getElementById("regularForm").style.display = "none";
    const btn = document.getElementById("revealCodeBtn");
    if (btn) btn.disabled = false;
    showReferralTeaser();
    initEnhancedMilestoneTracker();
    initScrollAnimations();
  } else {
    document.getElementById("freeReferralSection").style.display = "none";
    const rf = document.getElementById("regularForm");
    rf.style.display = "block";
    // Ensure contact inputs are visible and focused for the user
    try {
      const first =
        rf.querySelector('input[name="name"]') ||
        rf.querySelector('input[name="phone"]') ||
        rf.querySelector('input[name="email"]');
      if (first) {
        first.focus();
        first.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (e) {
      // ignore
    }
  }

  // Update offer-related buttons when filing type changes
  try {
    updateOfferButtons();
  } catch (e) {
    /* ignore */
  }
}

// Control visibility of promotional buttons (reveal/joker) based on filing type and step
function updateOfferButtons() {
  const confirmBtn = document.getElementById("jokerBtnConfirm");
  if (confirmBtn) {
    // Only show the Confirm-step 'Reveal Offer' when user explicitly chose Free Tax
    // and they are on the Confirm & Submit step (data-step="6"). Hide otherwise.
    try {
      confirmBtn.style.display =
        filingType === "free" && currentStep === 6 ? "" : "none";
    } catch (e) {
      confirmBtn.style.display = "none";
    }
  }

  // The free referral 'Reveal Code' button should only be visible for Free filings
  const revealBtn = document.getElementById("revealCodeBtn");
  if (revealBtn) revealBtn.style.display = filingType === "free" ? "" : "none";

  // Joker play button: always visible as a gamified tease; enable only when eligible
  const jokerBtn = document.getElementById("jokerPlayBtn");
  if (jokerBtn) {
    try {
      jokerBtn.style.display = "inline-flex";
      if (filingType === "free" && countCompleteReferrals() >= 5)
        jokerBtn.classList.remove("locked");
      else jokerBtn.classList.add("locked");
    } catch (e) {
      jokerBtn.style.display = "inline-flex";
      jokerBtn.disabled = true;
    }
  }
}

// wiring choice-type buttons
$$(".choice-type").forEach((b) =>
  b.addEventListener("click", () => {
    setFilingType(b.dataset.type);
    $$(".choice-type").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");

    // Safety: if user switches to Regular and contact fields are not filled,
    // clear any existing `submission_id` to avoid accidental creation/usage.
    if (b.dataset.type === "regular") {
      try {
        const nameEl = document.querySelector('[name="name"]');
        const phoneEl = document.querySelector('[name="phone"]');
        const emailEl = document.querySelector('[name="email"]');
        const hasName =
          nameEl && nameEl.value && nameEl.value.toString().trim().length > 0;
        const hasPhone =
          phoneEl &&
          (phoneEl.value || "").toString().replace(/\D/g, "").length >= 10;
        const hasEmail =
          emailEl && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailEl.value);
        if (!hasName || !hasPhone || !hasEmail) {
          submissionId = "";
          try {
            localStorage.removeItem("submission_id");
          } catch (e) {}
        }
      } catch (e) {
        // noop
      }
    }
  }),
);

function _normalizePhone(raw) {
  const s = (raw || "").toString();
  const digits = (s.match(/\d/g) || []).join("");
  return digits.length >= 10 ? digits.slice(-10) : digits;
}

function _isValidPhone(raw) {
  const p = _normalizePhone(raw);
  return /^\d{10}$/.test(p) && !/^0+$/.test(p);
}

function checkReferralsComplete() {
  for (let i = 1; i <= 5; i++) {
    const n =
      document.querySelector(`[name="ref_name_${i}"]`)?.value?.trim() || "";
    const pRaw =
      document.querySelector(`[name="ref_phone_${i}"]`)?.value?.trim() || "";
    if (!n || !_isValidPhone(pRaw)) return false;
  }
  return true;
}

function getReferrals() {
  const arr = [];
  for (let i = 1; i <= 5; i++) {
    const name =
      document.querySelector(`[name="ref_name_${i}"]`)?.value?.trim() || "";
    const phoneRaw =
      document.querySelector(`[name="ref_phone_${i}"]`)?.value?.trim() || "";
    const phone = _normalizePhone(phoneRaw);
    arr.push({ name, phone });
  }
  return arr;
}

// Unified reveal/generate referral code flow
async function revealReferralCode() {
  // Step 1: Validate referrer details for FREE tax
  const refName =
    document.querySelector('[name="referrer_name"]')?.value?.trim() || "";
  const refPhoneRaw =
    document.querySelector('[name="referrer_phone"]')?.value?.trim() || "";
  const refEmail =
    document.querySelector('[name="email"]')?.value?.trim() || "";
  const refPan = document.querySelector('[name="pan"]')?.value?.trim() || "";
  const cityType = document.querySelector('[name="city_type"]')?.value || "";

  const refPhone = _normalizePhone(refPhoneRaw);

  if (
    !refName ||
    !_isValidPhone(refPhone) ||
    !refEmail ||
    !refPan ||
    !cityType
  ) {
    alert(
      "Please fill all your details: Name, Phone (10 digits), Email, PAN, and City Type",
    );
    return;
  }

  // Step 2: Validate referrals
  if (!checkReferralsComplete()) {
    try {
      showPlayFairModal();
    } catch (e) {
      $("#freeMessage").textContent =
        "Please fill all 5 referrals with valid 10-digit phones.";
    }
    return;
  }

  // Step 3: If a code already exists, just show the modal
  const existing = localStorage.getItem("referral_code") || referralCode;
  if (existing) {
    referralCode = existing;
    showJokerModal();
    return;
  }

  // Step 4: Create submission if it doesn't exist (for FREE tax filing)
  if (!submissionId) {
    try {
      const result = await savePhase({
        filing_category: "free",
        name: refName,
        phone: refPhone,
        email: refEmail,
        pan: refPan,
        city_type: cityType,
      });
      if (result.submission_id) {
        submissionId = result.submission_id;
        localStorage.setItem("submission_id", submissionId);
      }
    } catch (e) {
      console.error("Failed to create submission:", e);
      alert("Failed to save your details. Please try again.");
      return;
    }
  }

  // Step 5: Generate referral code
  const namePrefix = refName
    .substring(0, 3)
    .toUpperCase()
    .replace(/[^A-Z]/g, "X");
  const randomSuffix = Math.random().toString(36).substr(2, 5).toUpperCase();
  const code = namePrefix + "_" + randomSuffix;

  referralCode = code;
  localStorage.setItem("referral_code", code);
  const rcEl = document.querySelector('[name="referral_code"]');
  if (rcEl) rcEl.value = code;
  $("#freeMessage").textContent =
    `Get your code at the end — share with your referrals.`;

  // Step 6: Save referral code and referrals to server
  try {
    await savePhase({
      submission_id: submissionId,
      referral_code: code,
      referrer_name: refName,
      referrals: JSON.stringify(getReferrals()),
    });
    console.log("[REFERRAL] Code saved to backend:", code);
  } catch (e) {
    console.warn("savePhase failed for referral code:", e);
  }

  // Step 7: Notify referrals via WhatsApp
  try {
    await fetch(`${API}/notify-referrals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        submission_id: submissionId,
        referrer_name: refName,
        referral_code: code,
        referrals: getReferrals(),
      }),
    });
  } catch (e) {
    console.warn("notify-referrals failed:", e);
  }
}

// Joker button click - same as reveal code but with celebration
document.getElementById("jokerPlayBtn")?.addEventListener("click", async () => {
  if (!checkReferralsComplete()) {
    showPlayFairModal();
    return;
  }
  // Trigger the same reveal flow
  await revealReferralCode();
});

// ── JOKER MODAL ──────────────────────────────────────────────────────────
function showJokerModal() {
  const modal = document.getElementById("jokerModal");
  const code = (referralCode || localStorage.getItem("referral_code") || "—")
    .toString()
    .toUpperCase();
  const spaced = code === "—" ? code : code.split("").join(" ");
  // restore celebratory content
  const titleEl = modal.querySelector(".joker-title");
  if (titleEl) titleEl.textContent = "CONGRATULATIONS!";
  const msgEl = modal.querySelector(".joker-msg");
  if (msgEl)
    msgEl.innerHTML =
      "You are the <b>6th Person</b> — your fees is <b>absolutely FREE!</b>";
  const codeEl = document.getElementById("jokerRevealCode");
  if (codeEl) {
    codeEl.style.display = "";
    codeEl.textContent = spaced;
  }
  const closeBtn = modal.querySelector(".joker-close-btn");
  if (closeBtn) closeBtn.textContent = "Claim My Free Filing";
  const rc = document.getElementById("refCode");
  if (rc) rc.textContent = code;
  modal.style.display = "flex";
}

function showPlayFairModal() {
  const modal = document.getElementById("jokerModal");
  const titleEl = modal.querySelector(".joker-title");
  if (titleEl) titleEl.textContent = "Let's Play Fair!";
  const msgEl = modal.querySelector(".joker-msg");
  if (msgEl)
    msgEl.innerHTML =
      '<span class="joker-tease">🃏 <b>Let\'s Play Fair!</b> Fill all 5 referrals and click again for your surprise... 🎭</span>';
  const codeEl = document.getElementById("jokerRevealCode");
  if (codeEl) codeEl.style.display = "none";
  const closeBtn = modal.querySelector(".joker-close-btn");
  if (closeBtn) closeBtn.textContent = "Okay";
  modal.style.display = "flex";
}

// keep the confirm button for the final step
document
  .getElementById("jokerBtnConfirm")
  ?.addEventListener("click", showJokerModal);

// Camera capture helpers
async function openCameraFor(inputId) {
  cameraTargetInput = document.getElementById(inputId);
  const modal = document.getElementById("cameraModal");
  modal.style.display = "flex";
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
      audio: false,
    });
    const v = document.getElementById("cameraVideo");
    v.srcObject = cameraStream;
    await v.play();
  } catch (e) {
    alert("Camera not available: " + e.message);
    modal.style.display = "none";
  }
}

function closeCamera() {
  const modal = document.getElementById("cameraModal");
  modal.style.display = "none";
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
}

document.getElementById("captureBtn")?.addEventListener("click", async () => {
  const v = document.getElementById("cameraVideo");
  const c = document.getElementById("cameraCanvas");
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  const ctx = c.getContext("2d");
  ctx.drawImage(v, 0, 0, c.width, c.height);
  c.toBlob(
    (blob) => {
      const f = new File([blob], `capture_${Date.now()}.jpg`, {
        type: "image/jpeg",
      });
      const dt = new DataTransfer();
      // keep existing files
      try {
        for (const f2 of cameraTargetInput.files) dt.items.add(f2);
      } catch (e) {}
      dt.items.add(f);
      cameraTargetInput.files = dt.files;
    },
    "image/jpeg",
    0.9,
  );
  closeCamera();
});

document.getElementById("closeCamera")?.addEventListener("click", closeCamera);

// attach camera btns
$$(".camera-btn").forEach((b) =>
  b.addEventListener("click", (e) => {
    const target = b.dataset.target;
    if (target) openCameraFor(target);
  }),
);

// ══════════════════════════════════════════════════════════════════════════
// DOCUMENT VERIFY MODAL
// ══════════════════════════════════════════════════════════════════════════

// Stores last extraction result per inputId
const _lastExtraction = {};

// Field definitions shown in the verify panel per doc type
const DV_FIELDS = {
  form16:   [{ k:"gross_salary",l:"Gross Salary" },{ k:"basic_salary",l:"Basic Salary" },{ k:"hra_received",l:"HRA Received" },{ k:"tds_paid",l:"TDS Paid" },{ k:"pf_employee",l:"PF (Employee)" },{ k:"professional_tax",l:"Professional Tax" },{ k:"pan",l:"PAN" }],
  payslip:  [{ k:"gross_salary",l:"Gross Salary" },{ k:"basic_salary",l:"Basic Salary" },{ k:"hra_received",l:"HRA Received" },{ k:"tds_paid",l:"TDS Paid" },{ k:"pf_employee",l:"PF (Employee)" },{ k:"pf_employer",l:"PF (Employer)" },{ k:"professional_tax",l:"Professional Tax" },{ k:"lta",l:"LTA" },{ k:"special_allowance",l:"Special Allowance" }],
  homeloan: [{ k:"home_loan_interest",l:"Interest (Annual)" },{ k:"home_loan_principal",l:"Principal (Annual)" },{ k:"bank_name",l:"Bank / Lender" },{ k:"loan_account_no",l:"Account No" },{ k:"loan_outstanding",l:"Outstanding Balance" }],
  insurance:[{ k:"premium_paid",l:"Premium Paid" },{ k:"policy_no",l:"Policy No" },{ k:"insurer_name",l:"Insurer" },{ k:"sum_assured",l:"Sum Assured" }],
  nps:      [{ k:"nps_pran",l:"PRAN Number" },{ k:"nps_self",l:"Employee Contribution" },{ k:"nps_employer",l:"Employer Contribution" }],
  school:   [{ k:"school_name",l:"School Name" },{ k:"school_fees",l:"Fees (Annual)" }],
  donation: [{ k:"org_name",l:"Organisation" },{ k:"donation_amount",l:"Amount Donated" }],
};
const DV_MONEY = new Set(["gross_salary","basic_salary","hra_received","tds_paid","pf_employee","pf_employer","professional_tax","lta","special_allowance","home_loan_interest","home_loan_principal","loan_outstanding","premium_paid","sum_assured","nps_self","nps_employer","school_fees","donation_amount"]);

function _dvVerifyBtn(inputId) {
  return `<button class="dv-verify-btn" onclick="openDocVerify('${inputId}')">📄 Verify</button>`;
}

function openDocVerify(inputId) {
  const input = document.getElementById(inputId);
  const ext = _lastExtraction[inputId];
  if (!input || !input.files.length) {
    alert("No file uploaded for this document yet.\nGo back to Step 2 or 3 and upload the file first.");
    return;
  }

  const files = Array.from(input.files);
  const tabsEl = document.getElementById("dvTabs");
  const fieldsEl = document.getElementById("dvFieldsInner");

  // Build file tabs
  window._dvFiles = files;
  window._dvUrls = files.map(f => URL.createObjectURL(f));
  tabsEl.innerHTML = files.map((f,i) =>
    `<button class="dv-tab${i===0?" active":""}" onclick="dvShowFile(${i})" title="${f.name}">${f.name}</button>`
  ).join("");
  dvShowFile(0);

  // Build extracted fields
  const docType = ext?.docType || "";
  const raw = ext?.data || {};
  const flat = { ...raw, ...(raw.income||{}), ...(raw.deductions||{}), ...(raw.personal||{}) };
  const defs = DV_FIELDS[docType] || [];

  if (defs.length) {
    fieldsEl.innerHTML = defs.map(({ k, l }) => {
      const v = flat[k];
      if (v === undefined || v === null || v === "" || v === 0) return "";
      const isMoney = DV_MONEY.has(k);
      const display = isMoney ? "₹" + Number(v).toLocaleString("en-IN") : v;
      return `<div class="dv-field">
        <div class="dv-field-label">${l}</div>
        <div class="dv-field-value${isMoney?" dv-money":""}">${display}</div>
      </div>`;
    }).join("") || '<div class="dv-no-data">No extracted values to display.</div>';
  } else {
    fieldsEl.innerHTML = '<div class="dv-no-data">Upload a file and extract to see values here.</div>';
  }

  document.getElementById("docVerifyModal").style.display = "flex";
  document.body.style.overflow = "hidden";
}

function dvShowFile(idx) {
  const frameEl = document.getElementById("dvFrame");
  const file = window._dvFiles[idx];
  const url = window._dvUrls[idx];
  document.querySelectorAll(".dv-tab").forEach((t,i) => t.classList.toggle("active", i===idx));
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  frameEl.innerHTML = isPdf
    ? `<iframe src="${url}"></iframe>`
    : `<img src="${url}" alt="${file.name}">`;
}

function closeDocVerify() {
  document.getElementById("docVerifyModal").style.display = "none";
  document.body.style.overflow = "";
}

// ── File preview buttons ──────────────────────────────────────────────────
// Automatically adds a "👁 Preview" button next to every file input.
// Button is hidden until a file is selected, then opens it in a new tab.
document.querySelectorAll('input[type="file"]').forEach((input) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "preview-btn";
  btn.innerHTML = "👁&nbsp; Preview File";
  btn.style.display = "none";
  btn.addEventListener("click", () => {
    const files = Array.from(input.files || []);
    if (!files.length) return;
    files.forEach((f) => window.open(URL.createObjectURL(f), "_blank"));
  });
  input.parentElement.insertBefore(btn, input.nextSibling);
  input.addEventListener("change", () => {
    btn.style.display = input.files && input.files.length ? "inline-block" : "none";
  });
});

// fetch winners for widget
async function loadWinners() {
  try {
    const r = await fetch(`${API}/winners`);
    const j = await r.json();
    const list = document.getElementById("winnersList");
    list.innerHTML = "";
    (j.winners || []).forEach((w) => {
      const li = document.createElement("li");
      li.textContent = `${w.name} — ${w.reward}`;
      list.appendChild(li);
    });
  } catch (e) {
    console.warn("winners load failed", e);
  }
}
loadWinners();

// Form16 toggle
$$(".choice").forEach((btn) => {
  btn.onclick = () => {
    $$(".choice").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    const val = btn.dataset.form16;

    document.querySelector("[name='has_form16']").value = val;

    $("#form16Section").style.display = val === "yes" ? "block" : "none";
    $("#payslipSection").style.display = "block";
  };
});

$("#next").onclick = async () => {
  // Prevent progressing from step 1 unless filing type is explicitly chosen
  if (currentStep === 1 && !filingType) {
    alert("Please select Regular Tax or Free Tax to continue.");
    return;
  }

  if (!validateStep(currentStep)) return;

  // STEP 1 → create submission (for REGULAR filing only)
  // FREE filing submission is created in revealReferralCode()
  if (currentStep === 1) {
    try {
      if (filingType === "regular") {
        const s1 = collectStep(1);
        const missing = [];
        if (!s1.name || !s1.name.toString().trim()) missing.push("name");
        const phoneDigits = (s1.phone || "").toString().replace(/\D/g, "");
        if (phoneDigits.length < 10) missing.push("phone");
        const mail = s1.email || "";
        const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!mail || !emailRe.test(mail)) missing.push("email");
        if (missing.length) {
          alert("Please fill required fields: " + missing.join(", "));
          return;
        }

        // Save submission for REGULAR filing
        await savePhase();
      } else if (filingType === "free") {
        // For FREE filing, auto-save Step 1 to generate referral code with correct name
        if (!referralCode && !localStorage.getItem("referral_code")) {
          try {
            const s1 = collectStep(1);
            // Referral flow uses referrer_name/referrer_phone, not name/phone
            const actualName = s1.referrer_name || s1.name;
            const actualPhone = s1.referrer_phone || s1.phone;

            const missing = [];
            if (!actualName || !actualName.toString().trim()) missing.push("name");
            const phoneDigits = (actualPhone || "").toString().replace(/\D/g, "");
            if (phoneDigits.length < 10) missing.push("phone");
            const mail = s1.email || "";
            const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!mail || !emailRe.test(mail)) missing.push("email");
            if (missing.length) {
              alert("Please fill required fields: " + missing.join(", "));
              return;
            }

            // Auto-save Step 1 data for FREE filing
            await savePhase({
              filing_category: "free",
              name: actualName,
              phone: actualPhone,
              email: s1.email,
              pan: s1.pan,
              city_type: s1.city_type,
            });
          } catch (e) {
            console.error("Step 1 auto-save failed:", e);
            alert("Failed to save your details. Please try again.");
            return;
          }
        }
        // Submission created via auto-save above
      } else {
        alert("Please select a filing type first.");
        return;
      }
    } catch (e) {
      // savePhase throws on server validation or network errors — do not advance
      console.error("Step 1 submission failed:", e);
      return;
    }
  }

  // STEP 2 → doc extract
  if (currentStep === 2) {
    await uploadDocs("form16", "form16");
    await uploadDocs("payslips", "payslip");
  }

  // STEP 3 → serialize structured proof JSON into hidden fields before saving
  if (currentStep === 3) {
    // Trigger extraction for all uploaded investment documents (if present)
    const jobs = [
      ["docHome", "homeloan", "homeLoanStatus"],
      ["docInsLife", "insurance", "lifeInsStatus"],
      ["docInsHealth", "insurance", "healthSelfStatus"],
      ["docNps", "nps", "npsStatus"],
      ["docSchool", "school", "schoolStatus"],
      ["docDon", "donation", "donationStatus"],
    ];

    for (const [inputId, docType, statusId] of jobs) {
      const inp = document.getElementById(inputId);
      if (inp && inp.files && inp.files.length) {
        try {
          await extractSection(inputId, docType, statusId);
        } catch (e) {
          console.warn("Extraction failed for", inputId, e);
        }
      }
    }

    // After extraction, serialize any created entries into the hidden JSON fields
    serializeAllInvestmentProofs();
  }

  // Avoid double-saving on step 1 (we already created submission earlier)
  if (currentStep !== 1) {
    await savePhase();
  }

  if (currentStep < TOTAL) {
    currentStep++;
    showStep(currentStep);
  }
};

$("#prev").onclick = () => {
  if (currentStep > 1) {
    currentStep--;
    showStep(currentStep);
  }
};

$("#submit").onclick = async () => {
  if (!$("#consent").checked) {
    alert("Please consent to continue.");
    return;
  }

  const all = {
    submission_id: submissionId,
  };

  for (let i = 1; i <= TOTAL; i++) {
    Object.assign(all, collectStep(i));
  }

  $("#submit").textContent = "Submitting...";
  $("#submit").disabled = true;

  try {
    const r = await fetch(`${API}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(all),
    });

    const j = await r.json();

    if (j.success) {
      // Store referral code for wallet and referral pages
      const refCode = j.referral_code || "—";
      localStorage.setItem("referral_code", refCode);

      $("#refCode").textContent = refCode;

      // Calculate and display refund options using actual backend-calculated values
      const amounts = calculateRefundAmounts({
        refund_old_a: j.refund_old_a,
        refund_old_b: j.refund_old_b,
        refund_old_c: j.refund_old_c,
      });
      // Store for later use in selectRefundOption
      refundAmounts = amounts;
      document.getElementById("optionA-amount").textContent =
        amounts.A.toLocaleString("en-IN");
      document.getElementById("optionB-amount").textContent =
        amounts.B.toLocaleString("en-IN");
      document.getElementById("optionC-amount").textContent =
        amounts.C.toLocaleString("en-IN");

      currentStep = 7;
      showStep(7);
    } else {
      alert("Error: " + j.error);
    }
  } catch (e) {
    alert("Network error: " + e.message);
  }

  $("#submit").textContent = "Submit";
  $("#submit").disabled = false;
};

// ── REFUND OPTION SELECTION ──────────────────────────────────────────────
function _inr(n) {
  return "₹" + Number(n || 0).toLocaleString("en-IN");
}

// Calculate refund amounts based on actual backend calculation
function calculateRefundAmounts(backendData = {}) {
  // If backend provides actual calculated refunds, use them
  if (backendData && backendData.refund_old_a !== undefined) {
    return {
      A: Math.round(backendData.refund_old_a || 0),
      B: Math.round(backendData.refund_old_b || 0),
      C: Math.round(backendData.refund_old_c || 0),
    };
  }

  // Fallback: Estimate refund (simplified: TDS - tax owed)
  // This is only used if backend data is not available
  const grossSalary = parseFloat(
    document.querySelector('[name="gross_salary"]')?.value || 0,
  );
  const tdsPaid = parseFloat(
    document.querySelector('[name="tds_paid"]')?.value || 0,
  );

  let estimatedRefund = tdsPaid * 0.85; // 85% of TDS as placeholder

  if (estimatedRefund < 5000) estimatedRefund = 5000;
  if (estimatedRefund > 200000) estimatedRefund = 200000;

  return {
    A: Math.round(estimatedRefund),
    B: Math.round(estimatedRefund * 0.98), // 2% fee
    C: Math.round(estimatedRefund * 1.075), // 7.5% interest over 6 months
  };
}

async function selectRefundOption(option) {
  if (!submissionId) {
    alert("Please complete the form first.");
    return;
  }

  try {
    const r = await fetch(`${API}/choose-option`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submission_id: submissionId, plan_id: option }),
    });

    const j = await r.json();

    if (!j.success) {
      alert(j.error || "Error saving choice.");
      return;
    }

    // Update UI to show selected option
    document.querySelectorAll(".option-card").forEach((card) => {
      card.classList.remove("selected");
    });
    document
      .querySelector(`.option-card[data-option="${option}"]`)
      ?.classList.add("selected");

    // Show payment instructions using stored amounts from submit
    const amount = refundAmounts[option];
    const descriptions = {
      A: "Direct bank transfer within 7-10 working days",
      B: "Expedited processing within 3-5 working days (₹500 fee)",
      C: "Invest for 6 months @ 7.5% and earn interest",
    };

    const upiId = j.payment_upi || "fairtaxadvisors@upi";
    const waMsg = encodeURIComponent(
      `Hi FairTax Team!\n\nI have selected Option ${option} for my refund.\n\nSubmission ID: ${submissionId}\nRefund Amount: ${_inr(amount)}\n\nKindly confirm. Thank you!`,
    );

    document.getElementById("quoteResult").innerHTML = `
      <div class="payment-card">
        <h3>✅ Option ${option} Selected!</h3>
        <p style="color:#166534;font-size:14px;margin-bottom:14px">
          ${descriptions[option]}
        </p>
        <div style="font-size:13px;color:#166534;margin-bottom:6px;font-weight:600">Your Refund Amount</div>
        <div class="payment-upi" style="font-size:28px;margin-bottom:6px">${_inr(amount)}</div>
        <div style="font-size:13px;color:#475569;margin-bottom:4px">Payment Required (50% upfront)</div>
        <div class="payment-upi" style="font-size:24px;margin-bottom:6px;color:#166534">${_inr(amount * 0.5)}</div>
        <div style="font-size:13px;color:#475569;margin-bottom:4px">UPI ID</div>
        <div style="font-size:16px;font-weight:800;color:#166534;margin-bottom:4px" id="upiDisplay">${upiId}</div>
        <button onclick="navigator.clipboard.writeText('${upiId}').then(()=>{document.getElementById('upiDisplay').textContent='Copied! ✓';}).catch(()=>{})"
          style="background:#e2e8f0;border:none;padding:5px 14px;border-radius:8px;cursor:pointer;font-size:12px;margin-bottom:16px">
          📋 Copy UPI ID
        </button>
        <br>
        <a class="payment-wa-btn" href="https://wa.me/917397510254?text=${waMsg}" target="_blank" rel="noopener">
          📱 Send Confirmation on WhatsApp →
        </a>
      </div>
    `;
  } catch (e) {
    alert("Network error: " + e.message);
  }
}

async function chooseOption(planId, fee, upfront) {
  try {
    const r = await fetch(`${API}/choose-option`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submission_id: submissionId, plan_id: planId }),
    });
    const j = await r.json();
    if (!j.success) {
      alert(j.error || "Error saving choice.");
      return;
    }

    const upiId = j.payment_upi || "fairtaxadvisors@upi";
    const waMsg = encodeURIComponent(
      `Hi FairTax Team!\n\nI have selected Plan ${planId} for my ITR filing.\n\nSubmission ID: ${submissionId}\nAmount to Pay (50% upfront): ${_inr(upfront)}\n\nKindly confirm. Thank you!`,
    );

    document.getElementById("quoteResult").innerHTML = `
      <div class="payment-card">
        <h3>✅ Plan ${planId} Selected!</h3>
        <p style="color:#166534;font-size:14px;margin-bottom:14px">
          Pay 50% upfront to begin filing. Remaining 50% is due <b>only after</b> your refund is credited.
        </p>
        <div style="font-size:13px;color:#166534;margin-bottom:6px;font-weight:600">Amount to Pay Now</div>
        <div class="payment-upi" style="font-size:28px;margin-bottom:6px">${_inr(upfront)}</div>
        <div style="font-size:13px;color:#475569;margin-bottom:4px">UPI ID</div>
        <div style="font-size:16px;font-weight:800;color:#166534;margin-bottom:4px" id="upiDisplay">${upiId}</div>
        <button onclick="navigator.clipboard.writeText('${upiId}').then(()=>{document.getElementById('upiDisplay').textContent='Copied! ✓';}).catch(()=>{})"
          style="background:#e2e8f0;border:none;padding:5px 14px;border-radius:8px;cursor:pointer;font-size:12px;margin-bottom:16px">
          📋 Copy UPI ID
        </button>
        <br>
        <a class="payment-wa-btn" href="https://wa.me/917397510254?text=${waMsg}" target="_blank" rel="noopener">
          📱 Send Payment Screenshot on WhatsApp →
        </a>
        <p style="font-size:11px;color:#64748b;margin-top:14px">
          Send your payment screenshot on WhatsApp to activate filing immediately.
          You can also <a href="status.html?id=${submissionId}" style="color:#2563eb">track your filing status here</a>.
        </p>
      </div>`;
  } catch (e) {
    alert("Network error: " + e.message);
  }
}

$("#checkQuote").onclick = async () => {
  const out = document.getElementById("quoteResult");
  out.innerHTML =
    '<p style="color:#64748b;text-align:center;padding:12px">⏳ Checking your quote status...</p>';

  try {
    const r = await fetch(`${API}/quote/${submissionId}`);
    const j = await r.json();

    if (!j.success) {
      out.innerHTML =
        '<div class="milestone-hint" style="margin:0">Submission not found. Please check your submission ID.</div>';
      return;
    }

    if (!j.approved) {
      out.innerHTML = `<div class="milestone-hint" style="margin:0">⏳ ${j.message || "Your filing is under expert review. You'll get a WhatsApp notification once approved!"}</div>`;
      return;
    }

    // For privacy and security the full quote PDF and plan details are only shared via WhatsApp.
    const quoteMsg = encodeURIComponent(
      `Hi FairTax Team,\n\nPlease share my quote for submission ID: ${submissionId}\n\nThank you!`,
    );
    const pdfUrl = j.pdf_url || "";
    const pdfLink = pdfUrl ? `\n\nQuote PDF: ${pdfUrl}` : "";

    out.innerHTML = `
      <div style="background:#eef2ff;border:2px solid #6366f1;border-radius:12px;padding:18px;text-align:center">
        <div style="font-size:18px;font-weight:800;color:#3730a3;margin-bottom:8px">✅ Quote Sent on WhatsApp</div>
        <div style="color:#374151;margin-bottom:10px">For confidentiality, your detailed quote and plan options have been sent to your WhatsApp number. Please check WhatsApp to view and download the secured report.</div>
        ${
          j.pdf_password
            ? `
        <div style="margin-top:12px;padding:12px;background:#fef3c7;border-radius:8px;border:1px solid #fcd34d">
          <div style="font-size:12px;color:#78350f;margin-bottom:6px;font-weight:600">PDF Password:</div>
          <div style="font-size:16px;color:#dc2608;font-weight:800;letter-spacing:2px;font-family:monospace">${j.pdf_password}</div>
        </div>`
            : ""
        }
        ${
          pdfUrl
            ? `
        <div style="margin-top:12px;padding:12px;background:#fff;border-radius:8px;text-align:left">
          <div style="font-size:12px;color:#6b7280;margin-bottom:8px">Your Quote PDF:</div>
          <a href="${pdfUrl}" target="_blank" style="color:#2563eb;text-decoration:underline;font-weight:600;word-break:break-all">
            ${pdfUrl.substring(pdfUrl.lastIndexOf("/") + 1)}
          </a>
        </div>`
            : ""
        }
        <div style="margin-top:8px">
          <a class="payment-wa-btn" href="https://wa.me/917397510254?text=${quoteMsg}" target="_blank" rel="noopener">📱 Contact Support on WhatsApp</a>
        </div>
        <p style="font-size:12px;color:#6b7280;margin-top:12px">You can also track filing progress on the <a href="status.html?id=${submissionId}" style="color:#2563eb">Status page</a>.</p>
      </div>`;
  } catch (e) {
    out.innerHTML = `<p style="color:#dc2626">Error: ${e.message}</p>`;
  }
};

// ── FREE ELIGIBILITY CHECKBOX ────────────────────────────────────────────
document
  .getElementById("freeEligibility")
  ?.addEventListener("change", function () {
    document.getElementById("eligibilityProof").style.display = this.checked
      ? "block"
      : "none";
  });

// ── MILESTONE REFERRAL TRACKER ───────────────────────────────────────────
const MILESTONES = [
  {
    count: 10,
    reward: "₹15,000",
    msg: "🌟 LEGENDARY! 10 referrals — you earn <b>₹15,000</b> cashback!",
    next: "You've unlocked the maximum reward!",
    mega: true,
  },
  {
    count: 5,
    reward: "₹5,000 + FREE Filing",
    msg: "🏆 Outstanding! 5 referrals — <b>FREE filing</b> + <b>₹5,000</b> cashback!",
    next: "Add 5 more to unlock ₹15,000!",
    mega: true,
  },
  {
    count: 3,
    reward: "₹1,000",
    msg: "🎊 Incredible! 3 referrals done — you earn <b>₹1,000</b> cashback!",
    next: "Add 2 more for ₹5,000 + FREE filing!",
  },
  {
    count: 1,
    reward: "₹250",
    msg: "🎉 Amazing! 1 referral done — you earn <b>₹250</b> cashback!",
    next: "Add 2 more for ₹1,000!",
  },
];

function countCompleteReferrals() {
  let count = 0;
  for (let i = 1; i <= 5; i++) {
    const n =
      document.querySelector(`[name="ref_name_${i}"]`)?.value?.trim() || "";
    const pRaw =
      document.querySelector(`[name="ref_phone_${i}"]`)?.value?.trim() || "";
    const p = _normalizePhone(pRaw);
    if (n && p && /^\d{10}$/.test(p)) count++;
  }
  return count;
}

function updateMilestoneTracker() {
  const tracker = document.getElementById("milestoneTracker");
  if (!tracker) return;
  const count = countCompleteReferrals();

  // Keep Joker CTA visible as a tease; enable it only when milestone reached
  const jokerBtn = document.getElementById("jokerPlayBtn");
  if (jokerBtn) {
    jokerBtn.style.display = "inline-flex";
    if (count >= 5) jokerBtn.classList.remove("locked");
    else jokerBtn.classList.add("locked");
  }

  if (count === 0) {
    tracker.innerHTML = `<div class="milestone-hint">🚀 Add your first referral to start earning!<br>
      <small>Refer 1 → ₹250 &nbsp;·&nbsp; Refer 3 → ₹1,000 &nbsp;·&nbsp; Refer 5 → FREE + ₹5,000 &nbsp;·&nbsp; Refer 10 → ₹15,000</small></div>`;
    return;
  }

  const reached = MILESTONES.find((m) => count >= m.count);
  // find next milestone (strictly greater than current count)
  const next = MILESTONES.find((m) => m.count > count);

  if (!reached) return;

  const rewardText = reached.reward || "";
  let nextText = next
    ? `Add ${next.count - count} more for ${next.reward}`
    : "You've unlocked the maximum reward!";

  tracker.innerHTML = `<div class="milestone-badge${reached.mega ? " mega" : ""}">
    🎉 <strong>${count}</strong> referrals done — <span style="font-weight:800">${rewardText}</span>
    <div class="milestone-next">👉 ${nextText}</div>
  </div>`;

  // If user completed 5 referrals and no referral code exists, auto-generate and reveal once
  if (count >= 5 && !localStorage.getItem("referral_code")) {
    if (!sessionStorage.getItem("auto_reveal_triggered")) {
      sessionStorage.setItem("auto_reveal_triggered", "1");
      try {
        revealReferralCode();
      } catch (e) {
        console.warn("auto reveal failed", e);
      }
    }
  }
}

// Attach milestone tracker to all referral inputs via delegation
document
  .getElementById("referralsList")
  ?.addEventListener("input", updateMilestoneTracker);

// Enable/disable "Reveal Code" button based on form completion
function updateRevealCodeButton() {
  const refName =
    document.querySelector('[name="referrer_name"]')?.value?.trim() || "";
  const refPhoneRaw =
    document.querySelector('[name="referrer_phone"]')?.value?.trim() || "";
  const refEmail =
    document.querySelector('[name="email"]')?.value?.trim() || "";
  const refPan = document.querySelector('[name="pan"]')?.value?.trim() || "";
  const cityType = document.querySelector('[name="city_type"]')?.value || "";
  const refPhone = _normalizePhone(refPhoneRaw);

  const referrerComplete =
    refName && _isValidPhone(refPhone) && refEmail && refPan && cityType;
  const referralsComplete = checkReferralsComplete();
  const btnEnabled = referrerComplete && referralsComplete;

  const btn = document.getElementById("revealCodeBtn");
  if (btn) {
    btn.disabled = !btnEnabled;
  }
}

// Attach to all relevant input fields
document
  .querySelector('[name="referrer_name"]')
  ?.addEventListener("input", updateRevealCodeButton);
document
  .querySelector('[name="referrer_phone"]')
  ?.addEventListener("input", updateRevealCodeButton);
document
  .querySelector('[name="email"]')
  ?.addEventListener("input", updateRevealCodeButton);
document
  .querySelector('[name="pan"]')
  ?.addEventListener("input", updateRevealCodeButton);
document
  .querySelector('[name="city_type"]')
  ?.addEventListener("change", updateRevealCodeButton);
document
  .getElementById("referralsList")
  ?.addEventListener("input", updateRevealCodeButton);

// ensure tracker initializes on page load in case fields are pre-filled
window.addEventListener("DOMContentLoaded", () => {
  updateMilestoneTracker();
  updateRevealCodeButton();
});

// ── STRUCTURED PROOF SECTION HELPERS ────────────────────────────────────
function toggleSection(id, val) {
  const el = document.getElementById(id);
  if (el) el.style.display = val === "yes" ? "block" : "none";
}

function addHomeLoan() {
  const list = document.getElementById("homeLoanList");
  const div = document.createElement("div");
  div.className = "entry-row";
  div.innerHTML = `
    <div class="entry-grid">
      <label>Loan Account / Policy No.<input class="hl-f" data-key="policy_no" placeholder="Account number"></label>
      <label>Sanction Date<input class="hl-f" data-key="sanction_date" type="date"></label>
      <label>Disbursed Amount (₹)<input class="hl-f" data-key="disbursed" type="number" placeholder="₹"></label>
      <label>Outstanding Amount (₹)<input class="hl-f" data-key="outstanding" type="number" placeholder="₹"></label>
      <label class="full-col">Bank / NBFC Name<input class="hl-f" data-key="bank_name" placeholder="e.g. SBI, HDFC Bank"></label>
    </div>
    <button type="button" class="remove-btn" onclick="this.closest('.entry-row').remove();serializeHomeLoan()">✕ Remove</button>`;
  list.appendChild(div);
}

function addInsurance(listId, type) {
  const list = document.getElementById(listId);
  const div = document.createElement("div");
  div.className = "entry-row";
  div.innerHTML = `
    <div class="entry-grid">
      <label>Insurance Company<input class="ins-f" data-key="company" data-type="${type}" placeholder="e.g. LIC, HDFC ERGO"></label>
      <label>Policy Number<input class="ins-f" data-key="policy_no" data-type="${type}" placeholder="Policy no."></label>
      <label class="full-col">Annual Premium (₹)<input class="ins-f" data-key="premium" data-type="${type}" type="number" placeholder="₹"></label>
    </div>
    <button type="button" class="remove-btn" onclick="this.closest('.entry-row').remove();serializeInsurance()">✕ Remove</button>`;
  list.appendChild(div);
}

function addDonation() {
  const list = document.getElementById("donationList");
  const div = document.createElement("div");
  div.className = "entry-row";
  div.innerHTML = `
    <div class="entry-grid">
      <label>Donee PAN<input class="don-f" data-key="donee_pan" style="text-transform:uppercase" placeholder="ABCDE1234F" maxlength="10"></label>
      <label>Institution Name<input class="don-f" data-key="institution" placeholder="Name of trust / org"></label>
      <label>Amount (₹)<input class="don-f" data-key="amount" type="number" placeholder="₹"></label>
      <label>Date<input class="don-f" data-key="date" type="date"></label>
    </div>
    <button type="button" class="remove-btn" onclick="this.closest('.entry-row').remove();serializeDonations()">✕ Remove</button>`;
  list.appendChild(div);
}

function serializeHomeLoan() {
  const data = Array.from(
    document.querySelectorAll("#homeLoanList .entry-row"),
  ).map((row) => {
    const obj = {};
    row.querySelectorAll(".hl-f").forEach((f) => {
      obj[f.dataset.key] = f.value;
    });
    return obj;
  });
  const el = document.getElementById("homeLoansJson");
  if (el) el.value = JSON.stringify(data);
}

function serializeInsurance() {
  const typeMap = {
    lifeInsList: "life",
    healthSelfList: "health_self",
    healthParentList: "health_parent",
  };
  const all = [];
  ["lifeInsList", "healthSelfList", "healthParentList"].forEach((listId) => {
    document.querySelectorAll(`#${listId} .entry-row`).forEach((row) => {
      const obj = { type: typeMap[listId] };
      row.querySelectorAll(".ins-f").forEach((f) => {
        obj[f.dataset.key] = f.value;
      });
      all.push(obj);
    });
  });
  const el = document.getElementById("insurancePoliciesJson");
  if (el) el.value = JSON.stringify(all);
}

function serializeDonations() {
  const data = Array.from(
    document.querySelectorAll("#donationList .entry-row"),
  ).map((row) => {
    const obj = {};
    row.querySelectorAll(".don-f").forEach((f) => {
      obj[f.dataset.key] = f.value;
    });
    // auto-sum sec_80g from donation amounts
    return obj;
  });
  const el = document.getElementById("donationsJson");
  if (el) el.value = JSON.stringify(data);
  // Auto-populate total 80G field
  const total = data.reduce((s, d) => s + (parseFloat(d.amount) || 0), 0);
  const g80 = document.querySelector('[name="sec_80g"]');
  if (g80 && !g80.dataset.manualOverride) g80.value = total || "";
}

function serializeAllInvestmentProofs() {
  serializeHomeLoan();
  serializeInsurance();
  serializeDonations();
}

// ── SPOUSE SECTION ───────────────────────────────────────────────────────
document.getElementById("showSpouseForm")?.addEventListener("click", () => {
  document.getElementById("spouseForm").style.display = "block";
  document.getElementById("showSpouseForm").style.display = "none";
});

document.getElementById("submitSpouse")?.addEventListener("click", async () => {
  const name = document.querySelector('[name="spouse_name"]')?.value?.trim();
  const pan = document.querySelector('[name="spouse_pan"]')?.value?.trim();
  const phone = document.querySelector('[name="spouse_phone"]')?.value?.trim();

  if (!name || !phone) {
    alert("Please enter spouse name and phone number.");
    return;
  }
  if (phone && !/^\d{10}$/.test(phone)) {
    alert("Phone must be 10 digits.");
    return;
  }

  const statusEl = document.getElementById("spouseStatus");
  statusEl.style.display = "block";
  statusEl.className = "status loading";
  statusEl.textContent = "Saving spouse details...";

  try {
    await fetch(`${API}/save-phase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        submission_id: submissionId,
        spouse_name: name,
        spouse_pan: pan,
        spouse_phone: phone,
        spouse_discount: "20",
      }),
    });
    statusEl.className = "status success";
    statusEl.textContent =
      "✅ Spouse details saved! 20% discount will be applied to their filing.";
    document.getElementById("submitSpouse").disabled = true;
  } catch (e) {
    statusEl.className = "status error";
    statusEl.textContent = "❌ Error saving: " + e.message;
  }
});

// ── MANUAL OVERRIDE FLAG for 80G ─────────────────────────────────────────
document
  .querySelector('[name="sec_80g"]')
  ?.addEventListener("input", function () {
    this.dataset.manualOverride = this.value ? "1" : "";
  });

// ── INLINE DOCUMENT EXTRACTION ───────────────────────────────────────────
async function extractSection(inputId, docType, statusId) {
  const input = document.getElementById(inputId);
  if (!input || !input.files.length) {
    alert("Please select a file first, then click Extract.");
    return;
  }

  const loader = document.getElementById("extractionLoader");
  const statusEl = document.getElementById(statusId);

  if (loader) {
    loader.style.display = "block";
    loader.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  if (statusEl) {
    statusEl.style.display = "block";
    statusEl.className = "status loading";
    statusEl.textContent = "🔍 AI reading document...";
  }

  const fd = new FormData();
  [...input.files].forEach((f) => fd.append("file", f));
  fd.append("doc_type", docType);

  try {
    // Use /api/itr/extract for proper ITR extraction
    const r = await fetch(`${API}/itr/extract`, { method: "POST", body: fd });
    const j = await r.json();

    if (j.success && j.data && Object.keys(j.data).length > 0) {
      fillInvestmentFields(j.data, docType);
      if (statusEl) {
        _lastExtraction[inputId] = { data: j.data, docType };
        statusEl.className = "status success";
        statusEl.innerHTML = `✅ Extracted! Review & confirm the fields below. ${_dvVerifyBtn(inputId)}`;
      }
    } else {
      if (statusEl) {
        statusEl.className = "status error";
        statusEl.textContent =
          "⚠️ Could not auto-extract — please fill fields manually.";
      }
    }
  } catch (err) {
    if (statusEl) {
      statusEl.className = "status error";
      statusEl.textContent = "❌ " + err.message;
    }
  } finally {
    if (loader) {
      loader.style.display = "none";
    }
  }
}

function fillInvestmentFields(data, docType) {
  const set = (name, val) => {
    const el = document.querySelector(`[name="${name}"]`);
    if (el && val && !el.value) el.value = val;
  };

  if (docType === "homeloan") {
    addHomeLoan();
    const rows = document.querySelectorAll("#homeLoanList .entry-row");
    const last = rows[rows.length - 1];
    if (last) {
      if (data.loan_account_no)
        last.querySelector('[data-key="policy_no"]').value =
          data.loan_account_no;
      if (data.bank_name)
        last.querySelector('[data-key="bank_name"]').value = data.bank_name;
      if (data.loan_outstanding)
        last.querySelector('[data-key="outstanding"]').value =
          data.loan_outstanding;
    }
    serializeHomeLoan();
    // Also store in hidden-compatible fields for calc
    if (data.home_loan_interest)
      set("home_loan_interest", data.home_loan_interest);
    if (data.home_loan_principal)
      set("home_loan_principal", data.home_loan_principal);
  } else if (docType === "nps") {
    set("nps_pran", data.nps_pran);
    set("nps_self", data.nps_self);
    set("nps_employer", data.nps_employer);
  } else if (docType === "school") {
    set("school_fees", data.school_fees);
  } else if (docType === "insurance") {
    const isHealth = (data.coverage_type || "")
      .toLowerCase()
      .includes("health");
    const listId = isHealth ? "healthSelfList" : "lifeInsList";
    const insType = isHealth ? "health_self" : "life";
    addInsurance(listId, insType);
    const rows = document.querySelectorAll(`#${listId} .entry-row`);
    const last = rows[rows.length - 1];
    if (last) {
      if (data.insurer_name)
        last.querySelector('[data-key="company"]').value = data.insurer_name;
      if (data.policy_no)
        last.querySelector('[data-key="policy_no"]').value = data.policy_no;
      if (data.premium_amount)
        last.querySelector('[data-key="premium"]').value = data.premium_amount;
    }
    serializeInsurance();
  } else if (docType === "donation") {
    addDonation();
    const rows = document.querySelectorAll("#donationList .entry-row");
    const last = rows[rows.length - 1];
    if (last) {
      if (data.donee_pan)
        last.querySelector('[data-key="donee_pan"]').value = data.donee_pan;
      if (data.organization_name)
        last.querySelector('[data-key="institution"]').value =
          data.organization_name;
      if (data.donation_amount)
        last.querySelector('[data-key="amount"]').value = data.donation_amount;
    }
    serializeDonations();
  }
}

// ─── PREMIUM ANIMATIONS & INTERACTIONS ───────────────────────────────────
// Scroll-triggered animations for form elements
function initScrollAnimations() {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = "1";
          entry.target.style.transform = "translateY(0)";
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.1, rootMargin: "0px 0px -50px 0px" },
  );

  $$(
    ".choice-buttons, .file, .grid label, .proof-section, .option-card",
  ).forEach((el) => {
    el.style.opacity = "0";
    el.style.transform = "translateY(20px)";
    el.style.transition = "opacity 0.5s ease, transform 0.5s ease";
    observer.observe(el);
  });
}

// Premium form field focus effects
function initPremiumFormInteractions() {
  $$("input, select, textarea").forEach((field) => {
    field.addEventListener("focus", () => {
      const parent = field.parentElement;
      if (parent) {
        parent.style.transition = "all 0.3s ease";
      }
    });
  });
}

// Premium button interactions
function initPremiumButtonEffects() {
  $$("button").forEach((btn) => {
    btn.addEventListener("mouseenter", function () {
      if (
        this.classList.contains("btn-primary") ||
        this.classList.contains("choice-type")
      ) {
        this.style.transform = "translateY(-4px)";
      }
    });

    btn.addEventListener("mouseleave", function () {
      this.style.transform = "none";
    });
  });
}

// Advanced form field interactions
function initAdvancedFormInteractions() {
  const formCard = document.querySelector("form");
  if (!formCard) return;

  // Add float labels effect
  $$("input, select, textarea").forEach((field) => {
    field.addEventListener("focus", function () {
      this.parentElement.style.background = "rgba(245,158,11,0.02)";
    });

    field.addEventListener("blur", function () {
      this.parentElement.style.background = "";
    });
  });
}

// Mobile optimization
function initMobileOptimizations() {
  const isMobile = window.innerWidth < 768;
  if (isMobile) {
    // Reduce animation duration on mobile for better performance
    document.documentElement.style.setProperty(
      "--transition",
      "150ms cubic-bezier(0.4, 0, 0.2, 1)",
    );
    document.documentElement.style.setProperty(
      "--transition-smooth",
      "200ms cubic-bezier(0.25, 0.46, 0.45, 0.94)",
    );

    // Make buttons larger on mobile
    $$("button").forEach((btn) => {
      btn.style.minHeight = "48px";
    });
  }
}

// Performance optimization - lazy load animations
function initPerformanceOptimizations() {
  // Use requestAnimationFrame for smoother animations
  if ("requestAnimationFrame" in window) {
    let animationFrameId = null;

    window.addEventListener("scroll", () => {
      if (animationFrameId === null) {
        animationFrameId = requestAnimationFrame(() => {
          // Trigger scroll animations
          $$(".scroll-fade-in:not(.visible)").forEach((el) => {
            const rect = el.getBoundingClientRect();
            if (rect.top < window.innerHeight * 0.8) {
              el.classList.add("visible");
            }
          });

          animationFrameId = null;
        });
      }
    });
  }
}

// Document extraction premium experience
function enhanceDocumentExtraction() {
  const form = document.querySelector("#taxForm");
  if (!form) return;

  // Removed auto-extraction loader on file change — only show during actual Next button extraction
}

// Initialize all premium effects
function initPremiumEffects() {
  initScrollAnimations();
  initPremiumFormInteractions();
  initPremiumButtonEffects();
  initAdvancedFormInteractions();
  initMobileOptimizations();
  initPerformanceOptimizations();
  enhanceDocumentExtraction();

  // Monitor referral changes
  $$('[name^="ref_name_"], [name^="ref_phone_"]').forEach((field) => {
    field.addEventListener("change", updateReferralTeaser);
    field.addEventListener("input", () => {
      // Trigger milestone update on input
      setTimeout(updateReferralTeaser, 300);
    });
  });
}

showStep(1);

// Initialize premium effects on DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPremiumEffects);
} else {
  initPremiumEffects();
}

// If page was opened from referral CTA, auto-open the user-details form
(function () {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("start") === "details") {
      setFilingType("regular");
      showStep(1);
      const nameInput = document.querySelector('[name="name"]');
      if (nameInput) {
        nameInput.focus();
        nameInput.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  } catch (e) {
    console.warn("start param handling failed", e);
  }
})();
// Adjust page spacing so sticky header/nav do not cover content when scrolling
function updateHeaderSpacing() {
  try {
    const header = document.querySelector("header");
    const nav = document.querySelector(".site-nav");
    let topOffset = 0;
    if (header) topOffset += header.offsetHeight;
    if (nav) topOffset += nav.offsetHeight;
    // Set CSS variables used by style.css to reserve space
    // Only set the spacing variables when header/nav are fixed or sticky
    const headerPos = header ? window.getComputedStyle(header).position : "";
    const navPos = nav ? window.getComputedStyle(nav).position : "";
    if (
      headerPos === "sticky" ||
      headerPos === "fixed" ||
      navPos === "sticky" ||
      navPos === "fixed"
    ) {
      document.documentElement.style.setProperty(
        "--site-top-offset",
        `${topOffset}px`,
      );
      document.documentElement.style.setProperty(
        "--main-top-offset",
        `${topOffset + 12}px`,
      );
    } else {
      document.documentElement.style.setProperty("--site-top-offset", `0px`);
      document.documentElement.style.setProperty("--main-top-offset", `0px`);
    }
  } catch (e) {
    // silently ignore in older browsers
    console.warn("updateHeaderSpacing failed", e);
  }
}

window.addEventListener("load", updateHeaderSpacing);
window.addEventListener("resize", updateHeaderSpacing);
// call once in case DOM is already ready
updateHeaderSpacing();
