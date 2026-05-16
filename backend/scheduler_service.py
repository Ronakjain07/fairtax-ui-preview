from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import sheets_service
import whatsapp_service

def _check_pending_reminders():
    """Every 12 h: WhatsApp-remind users who submitted 3 days ago and still haven't paid."""
    try:
        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return
        headers = vals[0]
        now = datetime.now()
        three_days_ago = now - timedelta(days=3)

        for row in vals[1:]:
            rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))

            # Skip if already paid or no need to remind
            if rec.get("payment_status", "").upper() == "PAID":
                continue

            ts_str = rec.get("timestamp", "")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
            except Exception:
                continue

            # Send reminder if exactly 3 days have passed
            if ts.date() == three_days_ago.date() or (ts < three_days_ago and (now - ts).days % 3 == 0):
                phone = rec.get("phone", "")
                name = rec.get("name", "there")
                submission_id = rec.get("submission_id", "")

                if phone:
                    wa = whatsapp_service.normalize_phone(phone)
                    try:
                        whatsapp_service.send_template(
                            wa,
                            "payment_reminder_3d",
                            [name, submission_id]
                        )
                        print(f"[Scheduler] Sent 3-day payment reminder to {phone}")
                    except Exception as e:
                        print(f"[Scheduler] Failed to send reminder: {e}")

    except Exception as e:
        print(f"[Scheduler] Reminder check error: {e}")


def _check_referral_updates():
    """Every 24 h: Send referral status updates to users."""
    try:
        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return

        headers = vals[0]

        for row in vals[1:]:
            rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))

            referral_code = rec.get("referral_code", "")
            phone = rec.get("phone", "")
            name = rec.get("name", "there")

            if not referral_code or not phone:
                continue

            try:
                # Get referral count
                rws = sheets_service._sheet("Referrals")
                rvals = rws.get_all_values()
                rcount = sum(
                    1 for rv in rvals[1:]
                    if len(rv) > 1 and rv[1].upper() == referral_code.upper() and rv[4].upper() == "CONFIRMED"
                )

                # Determine milestone message
                milestone_msg = ""
                if rcount >= 10:
                    milestone_msg = "🌟 You've hit LEGENDARY! ₹15,000 unlocked!"
                elif rcount >= 5:
                    milestone_msg = "🏆 FREE filing + ₹5,000 earned!"
                elif rcount >= 3:
                    milestone_msg = "🎊 ₹1,000 cashback unlocked!"
                elif rcount >= 1:
                    milestone_msg = f"🎉 {rcount} referral{'s' if rcount > 1 else ''} — keep sharing!"

                if milestone_msg and rcount > 0:
                    wa = whatsapp_service.normalize_phone(phone)
                    whatsapp_service.send_template(
                        wa,
                        "referral_update",
                        [name, str(rcount), milestone_msg]
                    )
                    print(f"[Scheduler] Sent referral update to {phone}: {rcount} referrals")

            except Exception as e:
                print(f"[Scheduler] Failed to send referral update: {e}")

    except Exception as e:
        print(f"[Scheduler] Referral update check error: {e}")


def _check_filing_completion():
    """Every 6 h: Check for filings that need completion notifications."""
    try:
        ws = sheets_service._sheet("Submissions")
        vals = ws.get_all_values()
        if len(vals) <= 1:
            return

        headers = vals[0]

        for row in vals[1:]:
            rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))

            filing_status = rec.get("filing_status", "").upper()
            payment_status = rec.get("payment_status", "").upper()
            phone = rec.get("phone", "")
            name = rec.get("name", "there")

            # Send notification if filing is complete
            if "FILED" in filing_status and payment_status == "PAID" and phone:
                try:
                    wa = whatsapp_service.normalize_phone(phone)
                    whatsapp_service.send_template(
                        wa,
                        "filing_completed",
                        [name, rec.get("submission_id", "")]
                    )
                    # Mark as notified to avoid duplicate sends
                    sheets_service.update_row(
                        rec,
                        {"filing_notification_sent": "1"}
                    )
                    print(f"[Scheduler] Sent filing completion notification to {phone}")
                except Exception as e:
                    print(f"[Scheduler] Failed to send filing notification: {e}")

    except Exception as e:
        print(f"[Scheduler] Filing completion check error: {e}")


def start_scheduler():
    """Initialize all scheduled tasks."""
    scheduler = BackgroundScheduler(daemon=True)

    # Payment reminders every 12 hours
    scheduler.add_job(
        _check_pending_reminders,
        "interval",
        hours=12,
        id="reminder_3d",
        name="3-day Payment Reminders"
    )

    # Referral updates every 24 hours
    scheduler.add_job(
        _check_referral_updates,
        "interval",
        hours=24,
        id="referral_updates",
        name="Referral Status Updates"
    )

    # Filing completion checks every 6 hours
    scheduler.add_job(
        _check_filing_completion,
        "interval",
        hours=6,
        id="filing_completion",
        name="Filing Completion Notifications"
    )

    scheduler.start()
    print("[Scheduler] ✅ Started with 3 automated tasks:")
    print("  • 3-day payment reminders (every 12h)")
    print("  • Referral status updates (every 24h)")
    print("  • Filing completion notifications (every 6h)")
    return scheduler
