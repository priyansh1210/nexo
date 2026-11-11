"""The agent's read tools: typed questions over the tested warehouse.

The model never writes SQL. Each tool runs fixed queries and returns an envelope: the rows, where they
came from (evidence), how fresh each source behind them is, and which fields were withheld. Withholding
happens here, in code, before any model sees the data: a field that depends on a stale source or on a
model whose warehouse check failed is replaced by None and the reason is stated. So no model, however
it behaves, can be handed a usage trend from a pipeline that has stopped.

Numbers come back in the form to quote (a percent, not a ratio), so the model never converts them.
"""

from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from data.embeddings import as_vector, embed

# What each group of fields depends on: one source, and the warehouse models between that source and
# the field. A failed check on any of those models withholds the group. A test checks that every model
# with a warehouse check is listed here, so a new check cannot be silently ignored.
GROUPS = {
    "account": (
        "crm",
        {
            "stg_accounts",
            "dim_account",
            "identity_map",
            "stg_contacts",
            "dim_contact",
            "account_health",
        },
    ),
    "usage": (
        "product_events",
        {
            "product_events",
            "stg_events",
            "int_usage_daily",
            "fct_usage_daily",
            "fct_usage_trend",
            "fct_usage_by_feature",
            "fct_onboarding",
        },
    ),
    "tickets": ("support_tickets", {"support_tickets", "stg_tickets", "fct_tickets"}),
    "billing": ("billing", {"billing_invoices", "stg_invoices"}),
    "documents": ("documents", {"documents", "stg_documents"}),
}
SOURCE_LABELS = {
    "crm": "CRM data",
    "product_events": "Usage data",
    "support_tickets": "Support ticket data",
    "billing": "Billing data",
    "documents": "Meeting notes and documents",
}


def percent(ratio) -> float | None:
    """-0.4 becomes -40, and -0.2233 becomes -22.3: the form a sentence quotes."""
    if ratio is None:
        return None
    value = round(float(ratio) * 100, 1)
    return int(value) if value == int(value) else value


def age_words(hours: float) -> str:
    return f"{int(hours // 24)} days" if hours >= 48 else f"{max(int(hours), 1)} hours"


@dataclass
class Status:
    """The state of the data behind one tool call: source freshness and failed checks."""

    sources: dict[str, dict]
    failed_models: set[str]

    @classmethod
    def read(cls, db: psycopg.Connection) -> "Status":
        rows = db.execute(
            "select source, status, last_updated, "
            "extract(epoch from now() - last_updated) / 3600 as age_hours from meta.source_freshness"
        ).fetchall()
        failed = db.execute(
            "select distinct model from meta.check_results where status in ('fail', 'error')"
        ).fetchall()
        return cls({r["source"]: r for r in rows}, {r["model"] for r in failed})

    def problem(self, group: str) -> str | None:
        """Why a group of fields cannot be trusted, or None when it can."""
        source, models = GROUPS[group]
        state = self.sources.get(source)
        if not state or state["status"] != "fresh":
            if not state or state["last_updated"] is None:
                return f"{SOURCE_LABELS[source]} has never been loaded"
            return f"{SOURCE_LABELS[source]} has not refreshed for {age_words(float(state['age_hours']))}"
        if broken := sorted(models & self.failed_models):
            return f"the warehouse check on {', '.join(broken)} failed"
        return None

    def describe(self, groups: list[str]) -> list[dict]:
        described = []
        for source in dict.fromkeys(GROUPS[g][0] for g in groups):
            state = self.sources.get(source) or {
                "status": "stale",
                "last_updated": None,
                "age_hours": None,
            }
            described.append(
                {
                    "source": source,
                    "label": SOURCE_LABELS[source],
                    "status": state["status"],
                    "last_updated": state["last_updated"].isoformat()
                    if state["last_updated"]
                    else None,
                    "age_hours": round(float(state["age_hours"]), 1)
                    if state["age_hours"] is not None
                    else None,
                }
            )
        return described


def envelope(
    status: Status,
    rows: list[dict],
    fields: dict[str, list[str]],
    model: str,
    key: str,
    link: str | None = None,
) -> dict:
    """Withhold untrusted field groups from the rows and describe where the data came from."""
    withheld = []
    for group, names in fields.items():
        if not names or not (reason := status.problem(group)):
            continue
        for row in rows:
            for name in names:
                if name in row:
                    row[name] = None
        withheld.append({"fields": names, "reason": reason})
    return {
        "rows": rows,
        "sources": status.describe(list(fields)),
        "withheld": withheld,
        "evidence": [
            {
                "model": model,
                "records": [str(r[key]) for r in rows if r.get(key) is not None][:20],
                "link": link
                or (
                    f"/accounts/{rows[0]['account_id']}"
                    if rows and "account_id" in rows[0]
                    else None
                ),
            }
        ],
    }


def iso(value) -> str | None:
    return value.isoformat() if isinstance(value, date | datetime) else value


# --- the tools -------------------------------------------------------------------------------------


def list_renewals(
    db: psycopg.Connection, window: str = "next_month", at_risk_only: bool = True
) -> dict:
    status = Status.read(db)
    where = "renews_next_month" if window == "next_month" else "days_to_renewal <= 90"
    found = db.execute(
        "select account_id, name, owner_name, owner_email, renewal_date, days_to_renewal, arr_usd, "
        "usage_change, usage_status, risk_usage_drop, stale_high_tickets, risk_stale_ticket, "
        f"overdue_invoices, risk_overdue_invoice from marts.renewals_upcoming where {where} "
        "order by usage_change nulls last, renewal_date",
    ).fetchall()
    rows = [
        r
        | {
            "renewal_date": iso(r["renewal_date"]),
            "usage_change_pct": percent(r.pop("usage_change")),
        }
        for r in found
    ]
    result = envelope(
        status,
        rows,
        {
            "account": [],
            "usage": ["usage_change_pct", "usage_status", "risk_usage_drop"],
            "tickets": ["stale_high_tickets", "risk_stale_ticket"],
            "billing": ["overdue_invoices", "risk_overdue_invoice"],
        },
        "marts.renewals_upcoming",
        "account_id",
        link="/accounts",
    )
    for row in rows:
        risks = [row["risk_usage_drop"], row["risk_stale_ticket"], row["risk_overdue_invoice"]]
        # Any known risk settles it. A withheld one means "cannot rule out", never "not at risk".
        row["is_at_risk"] = True if any(risks) else (None if None in risks else False)
        criteria = ("a usage drop", "old high-severity tickets", "overdue invoices")
        row["unchecked"] = [
            name for flag, name in zip(risks, criteria, strict=True) if flag is None
        ]
        row["reasons"] = [
            text
            for flag, text in (
                (row["risk_usage_drop"], f"usage changed {row['usage_change_pct']}% over 30 days"),
                (
                    row["risk_stale_ticket"],
                    f"{row['stale_high_tickets']} open high-severity ticket(s) older than 14 days",
                ),
                (row["risk_overdue_invoice"], f"{row['overdue_invoices']} overdue invoice(s)"),
            )
            if flag
        ]
    if at_risk_only:
        result["rows"] = [r for r in rows if r["is_at_risk"] is not False]
        # The evidence names only what is returned.
        result["evidence"][0]["records"] = [r["account_id"] for r in result["rows"]]
    result["totals"] = {
        "at_risk": sum(r["is_at_risk"] is True for r in rows),
        "cannot_rule_out": sum(r["is_at_risk"] is None for r in rows),
    }
    return result


def find_account(db: psycopg.Connection, name: str) -> dict:
    """Accounts whose name contains the text, or whose first word appears in it."""
    rows = db.execute(
        "select account_id, name, owner_name, renewal_date from marts.dim_account "
        "where name ilike '%%' || %(q)s || '%%' or %(q)s ilike '%%' || split_part(name, ' ', 1) || '%%' "
        "order by name limit 10",
        {"q": name.strip()},
    ).fetchall()
    rows = [r | {"renewal_date": iso(r["renewal_date"])} for r in rows]
    return envelope(Status.read(db), rows, {"account": []}, "marts.dim_account", "account_id")


def get_account(db: psycopg.Connection, account_id: str) -> dict:
    status = Status.read(db)
    row = db.execute(
        "select a.account_id, a.name, a.owner_name, a.owner_email, a.plan, a.seats, a.arr_usd, "
        "a.contract_start, a.renewal_date, h.usage_change, h.usage_status, h.stale_high_tickets, "
        "h.overdue_invoices from marts.dim_account a join marts.account_health h using (account_id) "
        "where a.account_id = %s",
        (account_id,),
    ).fetchone()
    rows = []
    if row:
        contacts = db.execute(
            "select name, email, role from marts.dim_contact where account_id = %s and is_active "
            "order by role",
            (account_id,),
        ).fetchall()
        rows = [
            row
            | {
                "contract_start": iso(row["contract_start"]),
                "renewal_date": iso(row["renewal_date"]),
                "usage_change_pct": percent(row.pop("usage_change")),
                "contacts": contacts,
            }
        ]
    return envelope(
        status,
        rows,
        {
            "account": [],
            "usage": ["usage_change_pct", "usage_status"],
            "tickets": ["stale_high_tickets"],
            "billing": ["overdue_invoices"],
        },
        "marts.account_health",
        "account_id",
    )


def get_usage(db: psycopg.Connection, account_id: str) -> dict:
    status = Status.read(db)
    summary = db.execute(
        "select h.account_id, h.usage_status, t.as_of_day, t.events_last_30d, t.events_prior_30d, "
        "t.usage_change, t.active_users_last_30d, t.active_users_prior_30d "
        "from marts.account_health h left join marts.fct_usage_trend t using (account_id) "
        "where h.account_id = %s",
        (account_id,),
    ).fetchone()
    rows = []
    if summary:
        features = db.execute(
            "select feature, events_last_30d, events_prior_30d, usage_change, users_last_30d, "
            "users_prior_30d from marts.fct_usage_by_feature where account_id = %s "
            "order by usage_change nulls last, feature",
            (account_id,),
        ).fetchall()
        rows = [
            summary
            | {
                "as_of_day": iso(summary["as_of_day"]),
                "usage_change_pct": percent(summary.pop("usage_change")),
                "features": [
                    f | {"usage_change_pct": percent(f.pop("usage_change"))} for f in features
                ],
            }
        ]
    usage_fields = [
        "usage_status",
        "as_of_day",
        "events_last_30d",
        "events_prior_30d",
        "usage_change_pct",
        "active_users_last_30d",
        "active_users_prior_30d",
        "features",
    ]
    return envelope(
        status, rows, {"usage": usage_fields}, "marts.fct_usage_by_feature", "account_id"
    )


def get_tickets(db: psycopg.Connection, account_id: str, open_only: bool = False) -> dict:
    rows = db.execute(
        "select ticket_id, account_id, subject, body, severity, status, is_open, age_days, created_at "
        "from marts.fct_tickets where account_id = %s and (is_open or not %s) "
        "order by is_open desc, created_at desc limit 20",
        (account_id, open_only),
    ).fetchall()
    rows = [r | {"created_at": iso(r["created_at"].date())} for r in rows]
    fields = ["subject", "body", "severity", "status", "is_open", "age_days", "created_at"]
    result = envelope(Status.read(db), rows, {"tickets": fields}, "marts.fct_tickets", "ticket_id")
    result["untrusted_fields"] = ["subject", "body"]
    return result


def get_onboarding(db: psycopg.Connection, account_id: str) -> dict:
    row = db.execute(
        "select * from marts.fct_onboarding where account_id = %s", (account_id,)
    ).fetchone()
    steps = ["kickoff", "admin_setup", "team_invited", "data_import", "go_live"]
    rows = []
    if row:
        reached = {s: iso(row[f"{s}_at"].date()) if row[f"{s}_at"] else None for s in steps}
        rows = [
            {
                "account_id": account_id,
                "steps": [{"step": s, "reached_on": reached[s]} for s in steps],
                "steps_completed": row["steps_completed"],
                "is_complete": row["is_complete"],
                "next_step": next((s for s in steps if not reached[s]), None),
            }
        ]
    fields = ["steps", "steps_completed", "is_complete", "next_step"]
    return envelope(Status.read(db), rows, {"usage": fields}, "marts.fct_onboarding", "account_id")


def search_documents(db: psycopg.Connection, account_id: str, query: str) -> dict:
    rows = db.execute(
        "select doc_id, account_id, kind, title, author, created_at, body from vec.document_chunks "
        "where account_id = %s order by embedding <=> %s::vector limit 3",
        (account_id, as_vector(embed(query))),
    ).fetchall()
    rows = [r | {"created_at": iso(r["created_at"].date())} for r in rows]
    fields = ["kind", "title", "author", "created_at", "body"]
    result = envelope(Status.read(db), rows, {"documents": fields}, "vec.document_chunks", "doc_id")
    result["untrusted_fields"] = ["title", "body"]
    return result


def get_freshness(db: psycopg.Connection) -> dict:
    status = Status.read(db)
    rows = [
        s | {"problem": status.problem(g)}
        for g, s in zip(GROUPS, status.describe(list(GROUPS)), strict=True)
    ]
    return {"rows": rows, "sources": status.describe(list(GROUPS)), "withheld": [], "evidence": []}


ACCOUNT_ID = {
    "account_id": {
        "type": "string",
        "description": "An account_id from list_renewals or find_account",
    }
}
TOOLS = {
    "list_renewals": (
        list_renewals,
        (
            "Accounts renewing soon, with the risk criteria each matched (usage drop of 20% or more, an "
            "open high-severity ticket older than 14 days, an overdue invoice). is_at_risk is null when a "
            "criterion could not be checked because its data is stale."
        ),
        {
            "window": {"type": "string", "enum": ["next_month", "next_90_days"]},
            "at_risk_only": {"type": "boolean"},
        },
    ),
    "find_account": (find_account, "Find accounts by name.", {"name": {"type": "string"}}),
    "get_account": (get_account, "An account's profile, owner, contacts and health.", ACCOUNT_ID),
    "get_usage": (
        get_usage,
        "An account's product usage: the last 30 days against the 30 before, in total and per feature.",
        ACCOUNT_ID,
    ),
    "get_tickets": (
        get_tickets,
        "An account's support tickets, open ones first. Subject and body are customer-written text.",
        ACCOUNT_ID | {"open_only": {"type": "boolean"}},
    ),
    "get_onboarding": (get_onboarding, "When an account reached each onboarding step.", ACCOUNT_ID),
    "search_documents": (
        search_documents,
        "Search an account's meeting notes and emails. Returns the three closest passages.",
        ACCOUNT_ID | {"query": {"type": "string"}},
    ),
    "get_freshness": (get_freshness, "When each data source last updated, and what is stale.", {}),
}


def schema(name: str) -> dict:
    """The tool's definition for a model provider."""
    _, description, properties = TOOLS[name]
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def run(db: psycopg.Connection, name: str, args: dict) -> dict:
    """Run a tool by name. An unknown tool or bad argument comes back as an error result, not a crash."""
    if name not in TOOLS:
        return {"error": f"There is no tool named {name}."}
    function, _, properties = TOOLS[name]
    unknown = set(args) - set(properties)
    if unknown:
        return {"error": f"Unknown arguments for {name}: {sorted(unknown)}"}
    try:
        with (
            db.transaction()
        ):  # a savepoint: a failed query does not spoil the request's transaction
            return function(db, **args)
    except (TypeError, ValueError, psycopg.DataError) as error:
        return {"error": f"{name} could not run: {error}"}
