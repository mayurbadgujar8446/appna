from __future__ import annotations
import os
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Tuple

from flask import Flask, flash, g, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["DATABASE"] = os.path.join(app.root_path, "smart_schedule.db")
app.config["SECRET_KEY"] = "smart-scheduling-secret-key"


@dataclass
class Task:
    """Represents a task interval used by the scheduling algorithm."""

    id: int
    name: str
    start_time: int
    end_time: int
    profit: int


def get_db() -> sqlite3.Connection:
    """Open a database connection for the current request context."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exception: Exception | None) -> None:
    """Close the database connection at the end of each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create the tasks table if it does not exist."""
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            profit INTEGER NOT NULL
        )
        """
    )
    db.commit()
    db.close()


def weighted_interval_scheduling(tasks: List[Task]) -> Tuple[List[Task], int]:
    """
    Weighted Interval Scheduling (Greedy + DP hybrid).

    Greedy step:
      1) Sort tasks by end_time.

    DP step:
      dp[i] = max(profit[i] + dp[last_non_conflicting], dp[i-1])

    Returns:
      (selected_tasks, total_profit)
    """
    if not tasks:
        return [], 0

    # Greedy sorting by task end time.
    tasks_sorted = sorted(tasks, key=lambda t: t.end_time)
    n = len(tasks_sorted)

    # For binary search: list of end times in sorted order.
    end_times = [task.end_time for task in tasks_sorted]

    # p[i] gives index of the last task that doesn't conflict with i, or -1.
    p = []
    for i in range(n):
        idx = bisect_right(end_times, tasks_sorted[i].start_time) - 1
        p.append(idx)

    # dp[i] = best profit using tasks up to index i.
    dp = [0] * n
    choose = [False] * n

    for i in range(n):
        include_profit = tasks_sorted[i].profit + (dp[p[i]] if p[i] >= 0 else 0)
        exclude_profit = dp[i - 1] if i > 0 else 0

        if include_profit > exclude_profit:
            dp[i] = include_profit
            choose[i] = True
        else:
            dp[i] = exclude_profit
            choose[i] = False

    # Backtrack to recover selected tasks.
    selected = []
    i = n - 1
    while i >= 0:
        include_profit = tasks_sorted[i].profit + (dp[p[i]] if p[i] >= 0 else 0)
        exclude_profit = dp[i - 1] if i > 0 else 0

        if include_profit > exclude_profit:
            selected.append(tasks_sorted[i])
            i = p[i]
        else:
            i -= 1

    selected.reverse()
    total_profit = dp[-1]
    return selected, total_profit


@app.route("/")
def dashboard():
    db = get_db()
    tasks = db.execute("SELECT * FROM tasks ORDER BY start_time, end_time").fetchall()
    total_tasks = len(tasks)
    total_profit = sum(task["profit"] for task in tasks)
    return render_template(
        "dashboard.html",
        tasks=tasks,
        total_tasks=total_tasks,
        total_profit=total_profit,
    )


@app.route("/tasks")
def view_tasks():
    db = get_db()
    tasks = db.execute("SELECT * FROM tasks ORDER BY start_time, end_time").fetchall()
    return render_template("tasks.html", tasks=tasks)


@app.route("/tasks/add", methods=["GET", "POST"])
def add_task():
    if request.method == "POST":
        name = request.form["name"].strip()
        start_time = int(request.form["start_time"])
        end_time = int(request.form["end_time"])
        profit = int(request.form["profit"])

        if end_time <= start_time:
            flash("End time must be greater than start time.", "danger")
            return redirect(url_for("add_task"))

        db = get_db()
        db.execute(
            "INSERT INTO tasks (name, start_time, end_time, profit) VALUES (?, ?, ?, ?)",
            (name, start_time, end_time, profit),
        )
        db.commit()
        flash("Task added successfully.", "success")
        return redirect(url_for("view_tasks"))

    return render_template("add_task.html", task=None, form_action=url_for("add_task"), page_title="Add Task")


@app.route("/tasks/edit/<int:task_id>", methods=["GET", "POST"])
def edit_task(task_id: int):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    if task is None:
        flash("Task not found.", "warning")
        return redirect(url_for("view_tasks"))

    if request.method == "POST":
        name = request.form["name"].strip()
        start_time = int(request.form["start_time"])
        end_time = int(request.form["end_time"])
        profit = int(request.form["profit"])

        if end_time <= start_time:
            flash("End time must be greater than start time.", "danger")
            return redirect(url_for("edit_task", task_id=task_id))

        db.execute(
            """
            UPDATE tasks
            SET name = ?, start_time = ?, end_time = ?, profit = ?
            WHERE id = ?
            """,
            (name, start_time, end_time, profit, task_id),
        )
        db.commit()
        flash("Task updated successfully.", "success")
        return redirect(url_for("view_tasks"))

    return render_template(
        "add_task.html",
        task=task,
        form_action=url_for("edit_task", task_id=task_id),
        page_title="Edit Task",
    )


@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id: int):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    flash("Task deleted successfully.", "success")
    return redirect(url_for("view_tasks"))


@app.route("/schedule")
def generate_schedule():
    db = get_db()
    rows = db.execute("SELECT * FROM tasks ORDER BY end_time").fetchall()

    tasks = [
        Task(
            id=row["id"],
            name=row["name"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            profit=row["profit"],
        )
        for row in rows
    ]

    selected_tasks, optimal_profit = weighted_interval_scheduling(tasks)

    return render_template(
        "schedule.html",
        all_tasks=rows,
        selected_tasks=selected_tasks,
        optimal_profit=optimal_profit,
    )


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)