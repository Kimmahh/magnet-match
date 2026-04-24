from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import connect as db_connect, is_postgres, placeholder_sql, row_value


BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "magnet-match-local-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "admin123")


def get_db() -> Any:
    if "db" not in g:
        g.db = db_connect()
    return g.db


@app.teardown_appcontext
def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def run_query(sql: str, params: tuple[Any, ...] = ()) -> Any:
    return get_db().execute(placeholder_sql(sql), params)


def run_many(sql: str, params_seq: list[tuple[Any, ...]]) -> None:
    if not params_seq:
        return

    db = get_db()
    statement = placeholder_sql(sql)
    if is_postgres():
        with db.cursor() as cursor:
            cursor.executemany(statement, params_seq)
    else:
        db.executemany(statement, params_seq)


def parse_numbers(raw_value: str) -> list[int]:
    values: set[int] = set()
    for token in raw_value.replace("\n", ",").replace(";", ",").split(","):
        stripped = token.strip()
        if stripped.isdigit():
            values.add(int(stripped))
    return sorted(values)


def parse_offer_list(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    return [int(item) for item in raw_value.split(",") if item.strip().isdigit()]


def format_numbers(values: list[int] | str) -> str:
    if isinstance(values, str):
        values = parse_offer_list(values)
    if not values:
        return "Aucun"
    return ", ".join(f"#{value}" for value in values)


def average_rating(user_id: int) -> float | None:
    row = run_query("SELECT AVG(rating) AS avg_rating FROM reviews WHERE target_user_id = ?", (user_id,)).fetchone()
    avg_rating = row_value(row, "avg_rating")
    if avg_rating is not None:
        return round(float(avg_rating), 1)
    return None


def current_user() -> Any:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return run_query("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required() -> Any:
    user = current_user()
    if not user:
        flash("Connecte-toi pour acceder a cette zone.", "warning")
        return None
    return user


def is_admin_candidate(user: Any | None) -> bool:
    if not user:
        return False
    return (user["username"] or "").strip().lower() == "kima"


def admin_logged_in() -> bool:
    return bool(session.get("admin_logged_in"))


def admin_required() -> bool:
    user = current_user()
    if not is_admin_candidate(user):
        flash("Acces admin reserve au compte autorise.", "warning")
        return False
    if not admin_logged_in():
        flash("Connecte-toi en admin pour acceder a cette page.", "warning")
        return False
    return True


def user_wishlist(user_id: int) -> list[int]:
    rows = run_query(
        "SELECT magnet_number FROM user_wishlist WHERE user_id = ? ORDER BY magnet_number",
        (user_id,),
    ).fetchall()
    return [row["magnet_number"] for row in rows]


def user_duplicates(user_id: int) -> list[int]:
    rows = run_query(
        "SELECT magnet_number FROM user_duplicates WHERE user_id = ? ORDER BY magnet_number",
        (user_id,),
    ).fetchall()
    return [row["magnet_number"] for row in rows]


def replace_collection(user_id: int, wishlist: list[int], duplicates: list[int]) -> None:
    db = get_db()
    db.execute(placeholder_sql("DELETE FROM user_wishlist WHERE user_id = ?"), (user_id,))
    db.execute(placeholder_sql("DELETE FROM user_duplicates WHERE user_id = ?"), (user_id,))
    run_many(
        "INSERT INTO user_wishlist (user_id, magnet_number) VALUES (?, ?)",
        [(user_id, value) for value in wishlist],
    )
    run_many(
        "INSERT INTO user_duplicates (user_id, magnet_number) VALUES (?, ?)",
        [(user_id, value) for value in duplicates],
    )
    db.commit()


def active_trade_rows(user_id: int) -> list[Any]:
    return run_query(
        """
        SELECT * FROM trades
        WHERE (requester_user_id = ? OR target_user_id = ?)
        AND status IN ('pending', 'accepted')
        """,
        (user_id, user_id),
    ).fetchall()


def reserved_numbers(user_id: int) -> dict[str, list[int]]:
    reserved_wishlist: set[int] = set()
    reserved_duplicates: set[int] = set()
    for trade in active_trade_rows(user_id):
        if trade["requester_user_id"] == user_id:
            reserved_wishlist.update(parse_offer_list(trade["offer_to_requester"]))
            reserved_duplicates.update(parse_offer_list(trade["offer_to_target"]))
        else:
            reserved_wishlist.update(parse_offer_list(trade["offer_to_target"]))
            reserved_duplicates.update(parse_offer_list(trade["offer_to_requester"]))
    return {
        "wishlist": sorted(reserved_wishlist),
        "duplicates": sorted(reserved_duplicates),
    }


def collection_state(user_id: int) -> dict[str, list[int]]:
    wishlist = user_wishlist(user_id)
    duplicates = user_duplicates(user_id)
    reserved = reserved_numbers(user_id)
    return {
        "wishlist_all": wishlist,
        "duplicates_all": duplicates,
        "wishlist_reserved": reserved["wishlist"],
        "duplicates_reserved": reserved["duplicates"],
        "wishlist_available": [value for value in wishlist if value not in reserved["wishlist"]],
        "duplicates_available": [value for value in duplicates if value not in reserved["duplicates"]],
    }


def remove_numbers_from_collection(user_id: int, wishlist_to_remove: list[int], duplicates_to_remove: list[int]) -> None:
    db = get_db()
    if wishlist_to_remove:
        run_many(
            "DELETE FROM user_wishlist WHERE user_id = ? AND magnet_number = ?",
            [(user_id, value) for value in wishlist_to_remove],
        )
    if duplicates_to_remove:
        run_many(
            "DELETE FROM user_duplicates WHERE user_id = ? AND magnet_number = ?",
            [(user_id, value) for value in duplicates_to_remove],
        )
    db.commit()


def compute_matches(for_user_id: int) -> list[dict[str, Any]]:
    me = run_query("SELECT * FROM users WHERE id = ?", (for_user_id,)).fetchone()
    if not me:
        return []

    my_collection = collection_state(for_user_id)
    wishlist = my_collection["wishlist_available"]
    duplicates = my_collection["duplicates_available"]
    if not wishlist and not duplicates:
        return []

    candidates = run_query("SELECT * FROM users WHERE id != ? ORDER BY username", (for_user_id,)).fetchall()
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_collection = collection_state(candidate["id"])
        candidate_wishlist = candidate_collection["wishlist_available"]
        candidate_duplicates = candidate_collection["duplicates_available"]
        offer_to_me = sorted(set(wishlist).intersection(candidate_duplicates))
        offer_to_them = sorted(set(duplicates).intersection(candidate_wishlist))
        if not offer_to_me and not offer_to_them:
            continue
        city_bonus = 10 if (candidate["city"] or "").strip().lower() == (me["city"] or "").strip().lower() else 0
        score = (len(offer_to_me) + len(offer_to_them)) * 20 + city_bonus
        existing_trade = run_query(
            """
            SELECT *
            FROM trades
            WHERE (
                (requester_user_id = ? AND target_user_id = ?)
                OR
                (requester_user_id = ? AND target_user_id = ?)
            )
            AND status NOT IN ('declined', 'cancelled', 'completed')
            ORDER BY id DESC
            LIMIT 1
            """,
            (for_user_id, candidate["id"], candidate["id"], for_user_id),
        ).fetchone()
        results.append(
            {
                "user": candidate,
                "offer_to_me": offer_to_me,
                "offer_to_them": offer_to_them,
                "score": score,
                "rating": average_rating(candidate["id"]),
                "existing_trade": existing_trade,
            }
        )
    return sorted(results, key=lambda item: item["score"], reverse=True)


def trade_counterpart(trade: Any, user_id: int) -> Any:
    other_user_id = trade["target_user_id"] if trade["requester_user_id"] == user_id else trade["requester_user_id"]
    return run_query("SELECT * FROM users WHERE id = ?", (other_user_id,)).fetchone()


def trade_messages(trade_id: int) -> list[Any]:
    return run_query(
        """
        SELECT messages.*, users.username
        FROM messages
        JOIN users ON users.id = messages.author_user_id
        WHERE trade_id = ?
        ORDER BY created_at
        """,
        (trade_id,),
    ).fetchall()


def my_trades(user_id: int) -> list[dict[str, Any]]:
    trades = run_query(
        """
        SELECT * FROM trades
        WHERE requester_user_id = ? OR target_user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id, user_id),
    ).fetchall()
    return [
        {
            "trade": trade,
            "counterpart": trade_counterpart(trade, user_id),
            "messages": trade_messages(trade["id"]),
        }
        for trade in trades
    ]


def create_trade(requester_id: int, target_id: int) -> int | None:
    matches = compute_matches(requester_id)
    selected = next((item for item in matches if item["user"]["id"] == target_id), None)
    if not selected:
        flash("Aucun echange pertinent trouve avec cette personne.", "warning")
        return None

    db = get_db()
    if is_postgres():
        cursor = db.execute(
            """
            INSERT INTO trades (
                requester_user_id,
                target_user_id,
                offer_to_requester,
                offer_to_target,
                requester_accepted,
                target_accepted,
                status
            ) VALUES (%s, %s, %s, %s, 1, 0, 'pending')
            RETURNING id
            """,
            (
                requester_id,
                target_id,
                ",".join(map(str, selected["offer_to_me"])),
                ",".join(map(str, selected["offer_to_them"])),
            ),
        )
        trade_id = cursor.fetchone()["id"]
    else:
        cursor = db.execute(
            """
            INSERT INTO trades (
                requester_user_id,
                target_user_id,
                offer_to_requester,
                offer_to_target,
                requester_accepted,
                target_accepted,
                status
            ) VALUES (?, ?, ?, ?, 1, 0, 'pending')
            """,
            (
                requester_id,
                target_id,
                ",".join(map(str, selected["offer_to_me"])),
                ",".join(map(str, selected["offer_to_them"])),
            ),
        )
        trade_id = cursor.lastrowid

    db.execute(
        placeholder_sql("INSERT INTO messages (trade_id, author_user_id, body) VALUES (?, ?, ?)"),
        (trade_id, requester_id, "Bonjour, ton profil semble compatible avec le mien. Partant pour cet echange ?"),
    )
    db.commit()
    flash("Demande d'echange envoyee. Les magnets concernes passent en reserve.", "success")
    return trade_id


@app.context_processor
def inject_globals() -> dict[str, Any]:
    return {
        "active_user": current_user(),
        "format_numbers": format_numbers,
        "admin_logged_in": admin_logged_in(),
        "admin_candidate": is_admin_candidate(current_user()),
    }


@app.route("/")
def home() -> str:
    user = current_user()
    if not user:
        return render_template("home.html")

    selected_trade_id = request.args.get("trade_id", type=int)
    trades = my_trades(user["id"])
    selected_trade = None
    if selected_trade_id:
        selected_trade = next((item for item in trades if item["trade"]["id"] == selected_trade_id), None)
    if selected_trade is None and trades:
        selected_trade = trades[0]

    open_chat = request.args.get("chat") == "1" and selected_trade is not None and selected_trade["trade"]["status"] == "accepted"
    return render_template(
        "dashboard.html",
        profile=user,
        collection=collection_state(user["id"]),
        matches=compute_matches(user["id"]),
        trades=trades,
        selected_trade=selected_trade,
        open_chat=open_chat,
        reviews=run_query(
            """
            SELECT reviews.*, author.username AS author_name, target.username AS target_name
            FROM reviews
            JOIN users AS author ON author.id = reviews.author_user_id
            JOIN users AS target ON target.id = reviews.target_user_id
            ORDER BY reviews.created_at DESC
            """
        ).fetchall(),
    )


@app.route("/admin")
def admin_dashboard() -> str:
    if not admin_required():
        return redirect(url_for("admin_login"))

    stats = {
        "users_total": row_value(run_query("SELECT COUNT(*) AS total FROM users").fetchone(), "total"),
        "trades_total": row_value(run_query("SELECT COUNT(*) AS total FROM trades").fetchone(), "total"),
        "trades_pending": row_value(run_query("SELECT COUNT(*) AS total FROM trades WHERE status = 'pending'").fetchone(), "total"),
        "trades_accepted": row_value(run_query("SELECT COUNT(*) AS total FROM trades WHERE status = 'accepted'").fetchone(), "total"),
        "trades_completed": row_value(run_query("SELECT COUNT(*) AS total FROM trades WHERE status = 'completed'").fetchone(), "total"),
        "messages_total": row_value(run_query("SELECT COUNT(*) AS total FROM messages").fetchone(), "total"),
        "reviews_total": row_value(run_query("SELECT COUNT(*) AS total FROM reviews").fetchone(), "total"),
    }

    latest_users = run_query(
        "SELECT username, city, email, created_at FROM users ORDER BY id DESC LIMIT 10"
    ).fetchall()

    return render_template("admin.html", stats=stats, latest_users=latest_users)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login() -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))
    if not is_admin_candidate(user):
        flash("Acces admin reserve au compte kima.", "warning")
        return redirect(url_for("home"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == app.config["ADMIN_PASSWORD"]:
            session["admin_logged_in"] = True
            flash("Connexion admin reussie.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Mot de passe admin incorrect.", "warning")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout() -> str:
    session.pop("admin_logged_in", None)
    flash("Deconnexion admin effectuee.", "success")
    return redirect(url_for("home"))


@app.route("/register", methods=["POST"])
def register() -> str:
    username = request.form["username"].strip()
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    city = request.form["city"].strip()

    existing = run_query("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        flash("Un compte existe deja avec cet email.", "warning")
        return redirect(url_for("home"))

    db = get_db()
    if is_postgres():
        cursor = db.execute(
            "INSERT INTO users (username, email, password_hash, city) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, email, generate_password_hash(password), city),
        )
        user_id = cursor.fetchone()["id"]
    else:
        cursor = db.execute(
            "INSERT INTO users (username, email, password_hash, city) VALUES (?, ?, ?, ?)",
            (username, email, generate_password_hash(password), city),
        )
        user_id = cursor.lastrowid
    db.commit()
    session["user_id"] = user_id
    flash("Compte cree avec succes.", "success")
    return redirect(url_for("home"))


@app.route("/login", methods=["POST"])
def login() -> str:
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    user = run_query("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Email ou mot de passe incorrect.", "warning")
        return redirect(url_for("home"))

    session["user_id"] = user["id"]
    flash("Connexion reussie.", "success")
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout() -> str:
    session.clear()
    flash("Deconnexion effectuee.", "success")
    return redirect(url_for("home"))


@app.route("/delete-account", methods=["POST"])
def delete_account() -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    user_id = user["id"]
    db = get_db()
    db.execute(placeholder_sql("DELETE FROM users WHERE id = ?"), (user_id,))
    db.commit()
    session.clear()
    flash("Ton compte a bien ete supprime.", "success")
    return redirect(url_for("home"))


@app.route("/profile", methods=["POST"])
def update_profile() -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    wishlist = parse_numbers(request.form.get("wishlist", ""))
    duplicates = parse_numbers(request.form.get("duplicates", ""))
    get_db().execute(
        placeholder_sql("UPDATE users SET username = ?, city = ?, email = ? WHERE id = ?"),
        (
            request.form["username"].strip(),
            request.form["city"].strip(),
            request.form["email"].strip().lower(),
            user["id"],
        ),
    )
    replace_collection(user["id"], wishlist, duplicates)
    flash("Profil mis a jour.", "success")
    return redirect(url_for("home"))


@app.route("/trade/create/<int:target_user_id>", methods=["POST"])
def start_trade(target_user_id: int) -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))
    trade_id = create_trade(user["id"], target_user_id)
    if trade_id:
        return redirect(url_for("home", trade_id=trade_id) + "#trades")
    return redirect(url_for("home") + "#matching")


@app.route("/trade/<int:trade_id>/accept", methods=["POST"])
def accept_trade(trade_id: int) -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    db = get_db()
    trade = run_query("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade:
        flash("Echange introuvable.", "warning")
        return redirect(url_for("home"))

    if trade["requester_user_id"] == user["id"]:
        db.execute(placeholder_sql("UPDATE trades SET requester_accepted = 1 WHERE id = ?"), (trade_id,))
    if trade["target_user_id"] == user["id"]:
        db.execute(placeholder_sql("UPDATE trades SET target_accepted = 1 WHERE id = ?"), (trade_id,))

    refreshed = run_query("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if refreshed["requester_accepted"] and refreshed["target_accepted"]:
        db.execute(placeholder_sql("UPDATE trades SET status = 'accepted' WHERE id = ?"), (trade_id,))
        db.execute(
            placeholder_sql("INSERT INTO messages (trade_id, author_user_id, body) VALUES (?, ?, ?)"),
            (trade_id, user["id"], "Parfait, l'echange est valide des deux cotes. On peut organiser la remise."),
        )
    db.commit()
    flash("Echange mis a jour.", "success")
    return redirect(url_for("home", trade_id=trade_id) + "#trades")


@app.route("/trade/<int:trade_id>/decline", methods=["POST"])
def decline_trade(trade_id: int) -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    get_db().execute(placeholder_sql("UPDATE trades SET status = 'cancelled' WHERE id = ?"), (trade_id,))
    get_db().commit()
    flash("Echange annule. Les magnets sont remis disponibles.", "success")
    return redirect(url_for("home", trade_id=trade_id) + "#trades")


@app.route("/trade/<int:trade_id>/message", methods=["POST"])
def send_message(trade_id: int) -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    body = request.form.get("body", "").strip()
    if not body:
        flash("Le message est vide.", "warning")
        return redirect(url_for("home", trade_id=trade_id) + "#chat")

    trade = run_query("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade:
        flash("Echange introuvable.", "warning")
        return redirect(url_for("home", trade_id=trade_id) + "#chat")

    if trade["status"] in ("declined", "cancelled"):
        flash("Le chat est ferme pour cet echange.", "warning")
        return redirect(url_for("home", trade_id=trade_id) + "#chat")

    get_db().execute(
        placeholder_sql("INSERT INTO messages (trade_id, author_user_id, body) VALUES (?, ?, ?)"),
        (trade_id, user["id"], body),
    )
    get_db().commit()
    return redirect(url_for("home", trade_id=trade_id, chat=1) + "#chat")


@app.route("/trade/<int:trade_id>/finalize", methods=["POST"])
def finalize_trade(trade_id: int) -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    decision = request.form.get("decision", "").strip()
    db = get_db()
    trade = run_query("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade or trade["status"] != "accepted":
        flash("Seuls les echanges acceptes peuvent etre finalises.", "warning")
        return redirect(url_for("home", trade_id=trade_id) + "#trades")

    if decision == "validated":
        remove_numbers_from_collection(
            trade["requester_user_id"],
            parse_offer_list(trade["offer_to_requester"]),
            parse_offer_list(trade["offer_to_target"]),
        )
        remove_numbers_from_collection(
            trade["target_user_id"],
            parse_offer_list(trade["offer_to_target"]),
            parse_offer_list(trade["offer_to_requester"]),
        )
        db.execute(placeholder_sql("UPDATE trades SET status = 'completed' WHERE id = ?"), (trade_id,))
        db.commit()
        flash("Echange valide. Les magnets concernes ont ete retires des listes.", "success")
    elif decision == "invalidated":
        db.execute(placeholder_sql("UPDATE trades SET status = 'cancelled' WHERE id = ?"), (trade_id,))
        db.commit()
        flash("Echange non valide. Les magnets sont remis disponibles.", "success")
    else:
        flash("Action inconnue.", "warning")

    return redirect(url_for("home", trade_id=trade_id) + "#trades")


@app.route("/review", methods=["POST"])
def create_review() -> str:
    user = login_required()
    if not user:
        return redirect(url_for("home"))

    trade_id = request.form.get("trade_id", type=int)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    trade = run_query("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    if not trade or trade["status"] not in ("accepted", "completed"):
        flash("Seuls les echanges acceptes ou valides peuvent etre notes.", "warning")
        return redirect(url_for("home"))

    target_user_id = trade["target_user_id"] if trade["requester_user_id"] == user["id"] else trade["requester_user_id"]
    existing = run_query("SELECT id FROM reviews WHERE trade_id = ? AND author_user_id = ?", (trade_id, user["id"])).fetchone()
    if existing:
        flash("Tu as deja laisse un avis pour cet echange.", "warning")
        return redirect(url_for("home"))

    get_db().execute(
        placeholder_sql("INSERT INTO reviews (trade_id, author_user_id, target_user_id, rating, comment) VALUES (?, ?, ?, ?, ?)"),
        (trade_id, user["id"], target_user_id, rating, comment),
    )
    get_db().commit()
    flash("Avis publie.", "success")
    return redirect(url_for("home"))


def init_db() -> None:
    schema_path = BASE_DIR / ("schema_postgres.sql" if is_postgres() else "schema.sql")
    db = db_connect()
    schema_text = schema_path.read_text(encoding="utf-8")
    if is_postgres():
        for statement in [part.strip() for part in schema_text.split(";") if part.strip()]:
            db.execute(statement)
    else:
        db.executescript(schema_text)
    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_ENV") != "production",
    )
