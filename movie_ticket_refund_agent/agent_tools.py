import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.adk.tools import ToolContext


DB_PATH = Path(__file__).resolve().parent / "movie_tickets.db"
IST = timezone(timedelta(hours=5, minutes=30))

# Policy Constants
MIN_ADVANCE_DAYS = 2          # Must request at least 2 calendar days before show date (1 day before = not eligible)
MAX_REFUNDABLE_TICKETS = 6    # Bulk bookings > 6 tickets are non-refundable online
MIN_REFUNDABLE_AMOUNT = 100   # Free/promotional vouchers are non-refundable
CREDIT_TIMELINE_TEXT = "3 to 4 working days to your original payment source account"


# ---------------------------------------
# Database helpers
# ---------------------------------------

@contextmanager
def database():
    if not DB_PATH.exists():
        raise FileNotFoundError(
            "movie_tickets.db was not found. "
            "Run dummy_db_creator.py first."
        )

    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def find_booking(connection, booking_id: str, user_id: str):
    return connection.execute(
        """
        SELECT
            b.*,
            m.title AS movie_title,
            m.language,
            m.format,
            m.release_date,
            m.ticket_price,
            u.name AS user_name,
            u.email AS user_email,
            u.phone AS user_phone
        FROM bookings b
        JOIN movies m ON b.movie_id = m.movie_id
        JOIN users u ON b.user_id = u.user_id
        WHERE b.booking_id = ? COLLATE NOCASE
          AND b.user_id = ?
        """,
        (booking_id.strip(), user_id),
    ).fetchone()


def email_required():
    return {
        "status": "email_required",
        "message": (
            "Please ask the user for the registered email address "
            "used while booking their movie tickets."
        ),
    }


def booking_not_found():
    return {
        "status": "not_found",
        "message": "This booking ID was not found under the selected user's account.",
    }


# ---------------------------------------
# Common refund policy evaluation
# ---------------------------------------

def evaluate_eligibility(booking):
    """Evaluate movie ticket refund eligibility using database records."""
    show_dt = datetime.fromisoformat(booking["show_datetime"])
    if show_dt.tzinfo is None:
        show_dt = show_dt.replace(tzinfo=IST)

    now = datetime.now(IST)
    days_until_show = (show_dt.date() - now.date()).days

    reasons = []

    if booking["status"] != "confirmed":
        reasons.append(
            f"Booking status is currently '{booking['status']}', not 'confirmed'."
        )

    if days_until_show < 0:
        reasons.append(
            "The movie show date has already passed."
        )
    elif days_until_show == 0:
        reasons.append(
            "Same-day show bookings are not eligible for a refund."
        )
    elif days_until_show < MIN_ADVANCE_DAYS:
        reasons.append(
            f"Refund requests are not allowed 1 day before the show "
            f"(show date is {show_dt.strftime('%d %b %Y')}; requests must be made at least {MIN_ADVANCE_DAYS} days prior)."
        )

    if booking["ticket_count"] > MAX_REFUNDABLE_TICKETS:
        reasons.append(
            f"Bulk bookings exceeding {MAX_REFUNDABLE_TICKETS} tickets ({booking['ticket_count']} tickets booked) are non-refundable online."
        )

    if booking["amount_paid"] < MIN_REFUNDABLE_AMOUNT:
        reasons.append(
            "Promotional or zero-value complimentary bookings are not eligible for a monetary refund."
        )

    eligible = len(reasons) == 0

    return {
        "booking_id": booking["booking_id"],
        "movie_title": booking["movie_title"],
        "theatre_name": booking["theatre_name"],
        "show_datetime": booking["show_datetime"],
        "days_until_show": days_until_show,
        "eligible": eligible,
        "reasons": reasons or [
            f"Booking is confirmed, requested {days_until_show} days before the show date (at least {MIN_ADVANCE_DAYS} days prior), and within ticket limits."
        ],
        "refund_amount": booking["amount_paid"] if eligible else 0,
        "currency": "INR",
    }


# ---------------------------------------
# Tool 1: Explain the common refund policy
# ---------------------------------------

def get_refund_policy() -> dict:
    """Return the movie ticket refund policy."""
    return {
        "minimum_advance_days_before_show": MIN_ADVANCE_DAYS,
        "one_day_before_show_allowed": False,
        "same_day_refund_allowed": False,
        "maximum_refundable_tickets_per_booking": MAX_REFUNDABLE_TICKETS,
        "promotional_free_tickets_refundable": False,
        "refund_amount": "100% of actual amount paid",
        "approval_mode": "Instant auto-approval upon confirmation",
        "refund_credit_timeline": CREDIT_TIMELINE_TEXT,
        "reason_required": True,
    }


# ---------------------------------------
# Tool 2: Identify user via email
# ---------------------------------------

def identify_user(
    email: str,
    tool_context: ToolContext,
) -> dict:
    """Look up a user using their registered email.

    Args:
        email: Email explicitly provided by the user.
    """
    tool_context.state["user_id"] = None
    tool_context.state["user_email"] = None

    email = email.strip().lower()

    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return {
            "status": "invalid_email",
            "message": "Please ask the user for a valid email address.",
        }

    with database() as connection:
        user = connection.execute(
            """
            SELECT user_id, name, email, phone
            FROM users
            WHERE email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()

    if user is None:
        return {
            "status": "not_found",
            "message": (
                "No account was found with this email. "
                "Ask the user to verify their registered email."
            ),
        }

    tool_context.state["user_id"] = user["user_id"]
    tool_context.state["user_email"] = user["email"]

    return {
        "status": "success",
        "user_id": user["user_id"],
        "name": user["name"],
        "email": user["email"],
        "phone": user["phone"],
    }


# ---------------------------------------
# Tool 3: Get the user's movie bookings
# ---------------------------------------

def get_my_bookings(
    tool_context: ToolContext,
) -> dict:
    """Return all movie ticket bookings for the identified user."""
    user_id = tool_context.state.get("user_id")
    if not user_id:
        return email_required()

    with database() as connection:
        rows = connection.execute(
            """
            SELECT
                b.booking_id,
                m.title AS movie_title,
                m.language,
                m.format,
                b.theatre_name,
                b.seat_numbers,
                b.ticket_count,
                b.show_datetime,
                b.booked_at,
                b.amount_paid,
                b.payment_method,
                b.transaction_id,
                b.status,
                b.refund_id
            FROM bookings b
            JOIN movies m ON b.movie_id = m.movie_id
            WHERE b.user_id = ?
            ORDER BY b.show_datetime DESC
            """,
            (user_id,),
        ).fetchall()

    return {
        "status": "success",
        "currency": "INR",
        "bookings": [dict(row) for row in rows],
    }


# ---------------------------------------
# Tool 4: Check refund eligibility
# ---------------------------------------

def check_refund_eligibility(
    booking_id: str,
    tool_context: ToolContext,
) -> dict:
    """Check whether a movie booking is eligible for a refund.

    Args:
        booking_id: Booking ID returned by get_my_bookings (e.g., BKG1001).
    """
    user_id = tool_context.state.get("user_id")
    if not user_id:
        return email_required()

    with database() as connection:
        booking = find_booking(connection, booking_id, user_id)
        if booking is None:
            return booking_not_found()

        return {
            "status": "success",
            **evaluate_eligibility(booking),
        }


# ---------------------------------------
# Tool 5: Submit and auto-approve refund request
# ---------------------------------------

def request_refund(
    booking_id: str,
    reason: str,
    tool_context: ToolContext,
) -> dict:
    """Initiate, record, and auto-approve a movie ticket refund after confirmation.

    Args:
        booking_id: Booking ID returned by get_my_bookings.
        reason: The refund reason supplied by the user. Never invent a reason.
    """
    user_id = tool_context.state.get("user_id")
    if not user_id:
        return email_required()

    reason = reason.strip()
    if not reason:
        return {
            "status": "reason_required",
            "message": "Ask the user to provide a reason for the refund.",
        }

    decision = check_refund_eligibility(booking_id, tool_context)
    if decision["status"] != "success":
        return decision

    if not decision["eligible"]:
        return {
            **decision,
            "status": "ineligible",
        }

    # ADK confirmation prompt
    confirmation = tool_context.tool_confirmation
    if confirmation is None:
        tool_context.request_confirmation(
            hint=(
                f"Confirm refund request for {decision['movie_title']} "
                f"(Booking ID: {decision['booking_id']}) for "
                f"INR {decision['refund_amount']}? "
                f"Reason: {reason}."
            ),
        )
        return {
            "status": "awaiting_confirmation",
        }

    if not confirmation.confirmed:
        return {
            "status": "cancelled",
            "message": "Refund request was cancelled by the user. No changes were saved.",
        }

    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")

        booking = find_booking(connection, booking_id, user_id)
        if booking is None:
            return booking_not_found()

        # Re-verify eligibility inside the transaction
        decision = evaluate_eligibility(booking)
        if not decision["eligible"]:
            return {
                "status": "ineligible",
                **decision,
            }

        now_iso = datetime.now(IST).isoformat()
        refund_id = f"RFD-{datetime.now(IST).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        refund_amount = booking["amount_paid"]

        # Step 1: Record initiation in DB
        connection.execute(
            """
            UPDATE bookings
            SET
                status = 'refund_requested',
                refund_id = ?,
                refund_reason = ?,
                refund_amount = ?,
                refund_initiated_at = ?
            WHERE booking_id = ?
              AND user_id = ?
              AND status = 'confirmed'
            """,
            (
                refund_id,
                reason,
                refund_amount,
                now_iso,
                booking["booking_id"],
                user_id,
            ),
        )

        # Step 2: Auto-approve immediately
        connection.execute(
            """
            UPDATE bookings
            SET
                status = 'refunded',
                refund_approved_at = ?,
                expected_credit_timeline = ?
            WHERE booking_id = ?
              AND user_id = ?
              AND status = 'refund_requested'
            """,
            (
                now_iso,
                CREDIT_TIMELINE_TEXT,
                booking["booking_id"],
                user_id,
            ),
        )

        return {
            "status": "refunded",
            "auto_approved": True,
            "refund_id": refund_id,
            "booking_id": booking["booking_id"],
            "transaction_id": booking["transaction_id"],
            "movie_title": booking["movie_title"],
            "theatre_name": booking["theatre_name"],
            "seat_numbers": booking["seat_numbers"],
            "show_datetime": booking["show_datetime"],
            "refund_amount": refund_amount,
            "currency": "INR",
            "payment_method": booking["payment_method"],
            "reason": reason,
            "refund_initiated_at": now_iso,
            "refund_approved_at": now_iso,
            "expected_credit_timeline": CREDIT_TIMELINE_TEXT,
            "message": (
                f"Your refund request (Refund ID: {refund_id}) has been initiated and auto-approved! "
                f"INR {refund_amount} will be credited to your {booking['payment_method']} source account within 3 to 4 working days."
            ),
        }


# ---------------------------------------
# Tool 6: Get complete A-to-Z refund status
# ---------------------------------------

def get_refund_status(
    booking_id: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """Return complete A-to-Z booking, payment, and refund status details from the database.

    Args:
        booking_id: Specific Booking ID (e.g., BKG1001). Leave empty to inspect all bookings for the user.
    """
    user_id = tool_context.state.get("user_id")
    if not user_id:
        return email_required()

    with database() as connection:
        if booking_id and booking_id.strip():
            booking = find_booking(connection, booking_id, user_id)
            if booking is None:
                return booking_not_found()

            records = [booking]
        else:
            records = connection.execute(
                """
                SELECT
                    b.*,
                    m.title AS movie_title,
                    m.language,
                    m.format,
                    m.release_date,
                    m.ticket_price,
                    u.name AS user_name,
                    u.email AS user_email,
                    u.phone AS user_phone
                FROM bookings b
                JOIN movies m ON b.movie_id = m.movie_id
                JOIN users u ON b.user_id = u.user_id
                WHERE b.user_id = ?
                ORDER BY
                    CASE b.status
                        WHEN 'refunded' THEN 1
                        WHEN 'refund_requested' THEN 2
                        ELSE 3
                    END,
                    b.show_datetime DESC
                """,
                (user_id,),
            ).fetchall()

        if not records:
            return {
                "status": "no_bookings",
                "message": "No bookings found for this user.",
            }

        detailed_records = []
        for b in records:
            is_refunded = b["status"] == "refunded"
            detailed_records.append(
                {
                    "booking_id": b["booking_id"],
                    "booking_status": b["status"],
                    "customer_details": {
                        "user_id": b["user_id"],
                        "name": b["user_name"],
                        "email": b["user_email"],
                        "phone": b["user_phone"],
                    },
                    "movie_and_show_details": {
                        "movie_id": b["movie_id"],
                        "movie_title": b["movie_title"],
                        "language": b["language"],
                        "format": b["format"],
                        "theatre_name": b["theatre_name"],
                        "seat_numbers": b["seat_numbers"],
                        "ticket_count": b["ticket_count"],
                        "show_datetime": b["show_datetime"],
                    },
                    "payment_details": {
                        "booked_at": b["booked_at"],
                        "amount_paid": b["amount_paid"],
                        "currency": "INR",
                        "payment_method": b["payment_method"],
                        "original_transaction_id": b["transaction_id"],
                    },
                    "refund_details": {
                        "refund_initiated": b["refund_id"] is not None,
                        "refund_id": b["refund_id"],
                        "refund_status": "Auto-Approved & Processed" if is_refunded else b["status"],
                        "refund_reason": b["refund_reason"],
                        "refund_amount": b["refund_amount"],
                        "currency": "INR",
                        "refund_initiated_at": b["refund_initiated_at"],
                        "refund_approved_at": b["refund_approved_at"],
                        "expected_credit_timeline": (
                            b["expected_credit_timeline"]
                            or (CREDIT_TIMELINE_TEXT if is_refunded else "N/A")
                        ),
                    },
                }
            )

        return {
            "status": "success",
            "total_records": len(detailed_records),
            "records": detailed_records,
        }