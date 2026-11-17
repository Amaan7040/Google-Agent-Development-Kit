import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Create the database alongside this script.
DB_PATH = Path(__file__).resolve().parent / "movie_tickets.db"

IST = timezone(timedelta(hours=5, minutes=30))


def setup_database():
    # Prevent accidental overwriting of existing data.
    if DB_PATH.exists():
        raise SystemExit(
            f"Database already exists: {DB_PATH}\n"
            "Delete it first if you want to recreate fresh dummy data."
        )

    now = datetime.now(IST).replace(minute=0, second=0, microsecond=0)

    def show_in_days(days, hour=19):
        target = now + timedelta(days=days)
        return target.replace(hour=hour, minute=30).isoformat()

    def days_ago(days, hour=14):
        target = now - timedelta(days=days)
        return target.replace(hour=hour, minute=15).isoformat()

    connection = sqlite3.connect(DB_PATH)

    try:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")

            # ----------------------------------
            # 1. Create the three tables
            # ----------------------------------
            connection.executescript("""
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    phone TEXT NOT NULL
                );

                CREATE TABLE movies (
                    movie_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    format TEXT NOT NULL,
                    release_date TEXT NOT NULL,
                    ticket_price INTEGER NOT NULL CHECK (ticket_price >= 0)
                );

                CREATE TABLE bookings (
                    booking_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    movie_id TEXT NOT NULL REFERENCES movies(movie_id),
                    theatre_name TEXT NOT NULL,
                    seat_numbers TEXT NOT NULL,
                    ticket_count INTEGER NOT NULL CHECK (ticket_count > 0),
                    show_datetime TEXT NOT NULL,
                    booked_at TEXT NOT NULL,
                    amount_paid INTEGER NOT NULL CHECK (amount_paid >= 0),
                    payment_method TEXT NOT NULL,
                    transaction_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK (
                            status IN (
                                'confirmed',
                                'refund_requested',
                                'refunded',
                                'cancelled'
                            )
                        ),
                    refund_id TEXT UNIQUE,
                    refund_reason TEXT,
                    refund_amount INTEGER NOT NULL DEFAULT 0 CHECK (refund_amount >= 0),
                    refund_initiated_at TEXT,
                    refund_approved_at TEXT,
                    expected_credit_timeline TEXT
                );
            """)

            # ----------------------------------
            # 2. Insert 5 latest/upcoming hyped movies
            # Prices are in whole INR per ticket.
            # ----------------------------------
            movies = [
                ("MOV001", "Ramayana: Part 1", "Hindi / Pan-India", "IMAX 3D", "2026-11-05", 550),
                ("MOV002", "Avengers: Doomsday", "English / Hindi", "IMAX 3D", "2026-12-18", 600),
                ("MOV003", "Dune: Part Three", "English", "IMAX 2D", "2026-12-18", 500),
                ("MOV004", "King", "Hindi", "2D", "2026-12-24", 420),
                ("MOV005", "Jumanji: Open World", "English / Hindi", "4DX", "2026-12-25", 480),
            ]

            connection.executemany(
                """
                INSERT INTO movies (
                    movie_id, title, language, format, release_date, ticket_price
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                movies,
            )

            # ----------------------------------
            # 3. Insert 10 users
            # ----------------------------------
            users = [
                ("USR001", "Rahul Sharma", "rahul@example.com", "+91-9811201101"),
                ("USR002", "Priya Singh", "priya@example.com", "+91-9811201102"),
                ("USR003", "Aman Gupta", "aman@example.com", "+91-9811201103"),
                ("USR004", "Neha Verma", "neha@example.com", "+91-9811201104"),
                ("USR005", "Vikram Mehta", "vikram@example.com", "+91-9811201105"),
                ("USR006", "Ananya Roy", "ananya@example.com", "+91-9811201106"),
                ("USR007", "Rohan Kapoor", "rohan@example.com", "+91-9811201107"),
                ("USR008", "Kavya Nair", "kavya@example.com", "+91-9811201108"),
                ("USR009", "Arjun Malhotra", "arjun@example.com", "+91-9811201109"),
                ("USR010", "Meera Joshi", "meera@example.com", "+91-9811201110"),
            ]

            connection.executemany(
                """
                INSERT INTO users (user_id, name, email, phone)
                VALUES (?, ?, ?, ?)
                """,
                users,
            )

            # ----------------------------------
            # 4. Insert 15 diverse bookings
            # Covers eligible, 1-day cutoff ineligible,
            # past show, bulk >6 tickets, and already refunded.
            # ----------------------------------
            bookings = [
                # USR001 (Rahul): 1 Eligible (4 days ahead), 1 Ineligible (1 day ahead)
                (
                    "BKG1001", "USR001", "MOV002",
                    "PVR Director's Cut, Ambience Mall", "G10, G11", 2,
                    show_in_days(4, 20), days_ago(3), 1200,
                    "UPI", "TXN202611001", "confirmed",
                    None, None, 0, None, None, None,
                ),
                (
                    "BKG1002", "USR001", "MOV001",
                    "INOX Insignia, Nehru Place", "D5, D6", 2,
                    show_in_days(1, 19), days_ago(4), 1100,
                    "Credit Card", "TXN202611002", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR002 (Priya): 1 Eligible (6 days ahead), 1 Past show (Ineligible)
                (
                    "BKG1003", "USR002", "MOV004",
                    "Cinepolis IMAX, DLF Avenue", "J14, J15, J16", 3,
                    show_in_days(6, 18), days_ago(2), 1260,
                    "UPI", "TXN202611003", "confirmed",
                    None, None, 0, None, None, None,
                ),
                (
                    "BKG1004", "USR002", "MOV001",
                    "PVR ICON, Promenade", "F8, F9", 2,
                    days_ago(2, 21), days_ago(6), 1100,
                    "Debit Card", "TXN202611004", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR003 (Aman): 1 Already Refunded, 1 Eligible (3 days ahead)
                (
                    "BKG1005", "USR003", "MOV003",
                    "PVR IMAX, Select CITYWALK", "H11, H12", 2,
                    show_in_days(5, 21), days_ago(4), 1000,
                    "UPI", "TXN202611005", "refunded",
                    "RFD-20261115-88A12C", "Travel plans changed suddenly", 1000,
                    days_ago(1, 11), days_ago(1, 11),
                    "3 to 4 working days to original payment source",
                ),
                (
                    "BKG1006", "USR003", "MOV005",
                    "Cinepolis 4DX, Unity One", "C4, C5", 2,
                    show_in_days(3, 17), days_ago(1), 960,
                    "NetBanking", "TXN202611006", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR004 (Neha): 1 Ineligible (Bulk booking > 6 tickets), 1 Eligible (2 days ahead boundary)
                (
                    "BKG1007", "USR004", "MOV002",
                    "PVR Superplex, Logix City Centre", "K1-K8", 8,
                    show_in_days(5, 19), days_ago(2), 4800,
                    "Credit Card", "TXN202611007", "confirmed",
                    None, None, 0, None, None, None,
                ),
                (
                    "BKG1008", "USR004", "MOV004",
                    "Miraj Cinemas, Subhash Nagar", "E7, E8", 2,
                    show_in_days(2, 20), days_ago(3), 840,
                    "UPI", "TXN202611008", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR005 (Vikram): 1 Eligible (7 days ahead)
                (
                    "BKG1009", "USR005", "MOV003",
                    "PVR IMAX, Vegas Mall", "L9, L10, L11, L12", 4,
                    show_in_days(7, 21), days_ago(1), 2000,
                    "Credit Card", "TXN202611009", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR006 (Ananya): 1 Ineligible (Same-day show)
                (
                    "BKG1010", "USR006", "MOV001",
                    "INOX Laserplex, Janakpuri", "B6, B7", 2,
                    show_in_days(0, 22), days_ago(5), 1100,
                    "UPI", "TXN202611010", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR007 (Rohan): 1 Eligible (5 days ahead)
                (
                    "BKG1011", "USR007", "MOV005",
                    "PVR 4DX, Pacific Mall", "D10, D11", 2,
                    show_in_days(5, 18), days_ago(2), 960,
                    "Debit Card", "TXN202611011", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR008 (Kavya): 1 Already Refunded
                (
                    "BKG1012", "USR008", "MOV004",
                    "PVR Plaza, Connaught Place", "F3, F4", 2,
                    show_in_days(8, 19), days_ago(3), 840,
                    "UPI", "TXN202611012", "refunded",
                    "RFD-20261116-49F01E", "Booked wrong theatre location", 840,
                    days_ago(1, 16), days_ago(1, 16),
                    "3 to 4 working days to original payment source",
                ),

                # USR009 (Arjun): 1 Ineligible (Promotional ₹0 ticket)
                (
                    "BKG1013", "USR009", "MOV002",
                    "PVR Gold, Vasant Kunj", "A1, A2", 2,
                    show_in_days(4, 20), days_ago(2), 0,
                    "Promo Voucher", "TXN202611013", "confirmed",
                    None, None, 0, None, None, None,
                ),

                # USR010 (Meera): 1 Eligible (3 days ahead), 1 Ineligible (1 day ahead)
                (
                    "BKG1014", "USR010", "MOV003",
                    "INOX IMAX, Vishal Mall", "G5, G6", 2,
                    show_in_days(3, 21), days_ago(2), 1000,
                    "Credit Card", "TXN202611014", "confirmed",
                    None, None, 0, None, None, None,
                ),
                (
                    "BKG1015", "USR010", "MOV005",
                    "PVR 4DX, Ambience Mall", "C8, C9", 2,
                    show_in_days(1, 16), days_ago(5), 960,
                    "UPI", "TXN202611015", "confirmed",
                    None, None, 0, None, None, None,
                ),
            ]

            connection.executemany(
                """
                INSERT INTO bookings (
                    booking_id, user_id, movie_id, theatre_name, seat_numbers,
                    ticket_count, show_datetime, booked_at, amount_paid,
                    payment_method, transaction_id, status, refund_id,
                    refund_reason, refund_amount, refund_initiated_at,
                    refund_approved_at, expected_credit_timeline
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                bookings,
            )

        print(f"Database created successfully: {DB_PATH}")
        for table in ("users", "movies", "bookings"):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  - {table}: {count} records")

    finally:
        connection.close()


if __name__ == "__main__":
    setup_database()