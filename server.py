import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

PAGERDUTY_API_KEY = os.environ["PAGERDUTY_API_KEY"]
BASE_URL = "https://api.pagerduty.com"

mcp = FastMCP("PagerDuty MCP")


def _headers() -> dict:
    return {
        "Authorization": f"Token token={PAGERDUTY_API_KEY}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


def _clean_assignment(assignment: dict) -> dict:
    """アサイン情報からPII(email/phone)を除外し、必要な情報のみ返す。"""
    assignee = assignment.get("assignee", {})
    return {
        "at": assignment.get("at"),
        "assignee_id": assignee.get("id"),
        "assignee_name": assignee.get("summary"),
        "assignee_type": assignee.get("type"),
    }


def _clean_incident(incident: dict) -> dict:
    """インシデントオブジェクトからPIIを除外して整形する。"""
    service = incident.get("service", {})
    escalation_policy = incident.get("escalation_policy", {})
    teams = incident.get("teams", [])

    return {
        "id": incident.get("id"),
        "incident_number": incident.get("incident_number"),
        "title": incident.get("title"),
        "status": incident.get("status"),
        "urgency": incident.get("urgency"),
        "created_at": incident.get("created_at"),
        "updated_at": incident.get("updated_at"),
        "html_url": incident.get("html_url"),
        "service": {
            "id": service.get("id"),
            "name": service.get("summary"),
        },
        "escalation_policy": {
            "id": escalation_policy.get("id"),
            "name": escalation_policy.get("summary"),
        },
        "teams": [
            {"id": t.get("id"), "name": t.get("summary")} for t in teams
        ],
        "assignments": [
            _clean_assignment(a) for a in incident.get("assignments", [])
        ],
        "acknowledgements": [
            {
                "at": ack.get("at"),
                "acknowledger_id": ack.get("acknowledger", {}).get("id"),
                "acknowledger_name": ack.get("acknowledger", {}).get("summary"),
            }
            for ack in incident.get("acknowledgements", [])
        ],
    }


@mcp.tool()
async def list_recent_incidents(
    status: Optional[str] = "triggered,acknowledged",
    days: int = 7,
    limit: int = 25,
) -> dict:
    """最近のインシデント一覧を取得する。

    Args:
        status: カンマ区切りのステータス。triggered/acknowledged/resolved から指定。
                デフォルトは "triggered,acknowledged"（未解決のもの）。
                すべて取得する場合は "triggered,acknowledged,resolved"。
        days: 何日前からのインシデントを取得するか（デフォルト: 7日）。
        limit: 取得件数の上限（1〜100、デフォルト: 25）。
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    statuses = [s.strip() for s in status.split(",")]

    params: dict = {
        "limit": min(limit, 100),
        "since": since,
        "sort_by": "created_at:desc",
    }
    for s in statuses:
        params.setdefault("statuses[]", [])
        if isinstance(params["statuses[]"], list):
            params["statuses[]"].append(s)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/incidents",
            headers=_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    incidents = [_clean_incident(i) for i in data.get("incidents", [])]
    return {
        "total": data.get("total", len(incidents)),
        "limit": data.get("limit"),
        "offset": data.get("offset"),
        "incidents": incidents,
    }


@mcp.tool()
async def get_incident(incident_id: str) -> dict:
    """指定したインシデントの詳細を取得する。

    Args:
        incident_id: PagerDuty インシデントID（例: "P1234567"）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/incidents/{incident_id}",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    return _clean_incident(data.get("incident", {}))


@mcp.tool()
async def get_incident_notes(incident_id: str) -> dict:
    """インシデントに付いているノート（コメント）一覧を取得する。

    Args:
        incident_id: PagerDuty インシデントID（例: "P1234567"）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/incidents/{incident_id}/notes",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    notes = [
        {
            "id": n.get("id"),
            "content": n.get("content"),
            "created_at": n.get("created_at"),
            "channel": n.get("channel", {}).get("summary"),
        }
        for n in data.get("notes", [])
    ]
    return {"incident_id": incident_id, "notes": notes}


@mcp.tool()
async def get_incident_log_entries(
    incident_id: str,
    limit: int = 20,
) -> dict:
    """インシデントのログエントリ（状態変化・通知の履歴）を取得する。

    Args:
        incident_id: PagerDuty インシデントID（例: "P1234567"）。
        limit: 取得件数の上限（デフォルト: 20）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/incidents/{incident_id}/log_entries",
            headers=_headers(),
            params={"limit": min(limit, 100)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    entries = [
        {
            "id": e.get("id"),
            "type": e.get("type"),
            "summary": e.get("summary"),
            "created_at": e.get("created_at"),
            "channel": e.get("channel", {}).get("type"),
        }
        for e in data.get("log_entries", [])
    ]
    return {"incident_id": incident_id, "log_entries": entries}


@mcp.tool()
async def list_services(limit: int = 25) -> dict:
    """PagerDuty に登録されているサービス一覧を取得する。

    Args:
        limit: 取得件数の上限（1〜100、デフォルト: 25）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/services",
            headers=_headers(),
            params={"limit": min(limit, 100), "sort_by": "name"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    services = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "status": s.get("status"),
            "description": s.get("description"),
            "html_url": s.get("html_url"),
            "escalation_policy": {
                "id": s.get("escalation_policy", {}).get("id"),
                "name": s.get("escalation_policy", {}).get("summary"),
            },
            "teams": [
                {"id": t.get("id"), "name": t.get("summary")}
                for t in s.get("teams", [])
            ],
        }
        for s in data.get("services", [])
    ]
    return {
        "total": data.get("total", len(services)),
        "services": services,
    }


@mcp.tool()
async def list_teams(limit: int = 25) -> dict:
    """PagerDuty に登録されているチーム一覧を取得する。

    Args:
        limit: 取得件数の上限（1〜100、デフォルト: 25）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/teams",
            headers=_headers(),
            params={"limit": min(limit, 100)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    teams = [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "description": t.get("description"),
            "html_url": t.get("html_url"),
        }
        for t in data.get("teams", [])
    ]
    return {
        "total": data.get("total", len(teams)),
        "teams": teams,
    }


@mcp.tool()
async def list_escalation_policies(limit: int = 25) -> dict:
    """エスカレーションポリシー一覧を取得する。

    Args:
        limit: 取得件数の上限（1〜100、デフォルト: 25）。
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/escalation_policies",
            headers=_headers(),
            params={"limit": min(limit, 100), "sort_by": "name"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    policies = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description"),
            "num_loops": p.get("num_loops"),
            "teams": [
                {"id": t.get("id"), "name": t.get("summary")}
                for t in p.get("teams", [])
            ],
        }
        for p in data.get("escalation_policies", [])
    ]
    return {
        "total": data.get("total", len(policies)),
        "escalation_policies": policies,
    }


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8007)
