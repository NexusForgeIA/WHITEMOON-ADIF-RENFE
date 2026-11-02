"""Malla horaria de peligros: cuántos peligros detectó RailGuard en cada hora del día (hora de Madrid), por severidad, en los últimos
N días. Sale del registro de auditoría (eventos HAZARD). Se excluyen los trenes sintéticos de la simulación (T-9xxx).
Informativo: describe lo ocurrido, no predice ni interviene en las barreras."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
SEVS = ("CAUTION", "RESTRICT", "STOP")


def _synthetic(trains):
    return bool(trains) and all(str(t).startswith("T-") for t in trains)


def hourly(records, days=7, now_ms=None):
    """records: iterable de {'e': evento}. Devuelve {'days', 'total', 'hours': [{h, CAUTION, RESTRICT, STOP, n}], 'peak'}."""
    now_ms = now_ms or int(datetime.now(TZ).timestamp() * 1000)
    since = now_ms - days * 86400_000
    hrs = [{"h": i, **{s: 0 for s in SEVS}, "n": 0} for i in range(24)]
    total = 0
    for r in records:
        e = r.get("e", r)
        if e.get("kind") != "HAZARD" or not (since <= e.get("t", 0) <= now_ms) or _synthetic(e.get("trains")):
            continue
        sev = e.get("sev")
        if sev not in SEVS:
            continue
        b = hrs[datetime.fromtimestamp(e["t"] / 1000, TZ).hour]
        b[sev] += 1
        b["n"] += 1
        total += 1
    peak = max(hrs, key=lambda b: b["n"])["h"] if total else None
    return {"days": days, "total": total, "hours": hrs, "peak": peak}
